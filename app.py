import os
import random
import smtplib
from datetime import date, datetime, timedelta
from functools import wraps
import resend
import requests
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(override=True)

print("DATABASE URL FOUND:", bool(os.getenv("DATABASE_URL")))
print("DATABASE URL STARTS:", (os.getenv("DATABASE_URL") or "")[:20])

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key")

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def get_db():
    return psycopg2.connect(
        os.getenv("DATABASE_URL"),
        cursor_factory=RealDictCursor
    )


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def days_left(expiry_date):
    return (expiry_date - date.today()).days


def document_status(expiry_date):
    d = days_left(expiry_date)
    if d < 0:
        return "Expired"
    if d <= 7:
        return "Critical"
    if d <= 30:
        return "Expiring Soon"
    return "Active"


@app.context_processor
def utility_processor():
    return {
        "days_left": days_left,
        "document_status": document_status
    }


@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")



def send_otp_email(recipient, otp):
    brevo_api_key = os.getenv("BREVO_API_KEY")
    sender_email = os.getenv("SMTP_USER")

    if not brevo_api_key or not sender_email:
        print("BREVO_API_KEY or sender email is missing")
        return False

    try:
        url = "https://api.brevo.com/v3/smtp/email"

        headers = {
            "accept": "application/json",
            "api-key": brevo_api_key,
            "content-type": "application/json"
        }

        data = {
            "sender": {
                "name": "Document Expiry Tracker",
                "email": sender_email
            },
            "to": [
                {
                    "email": recipient
                }
            ],
            "subject": "Your Document Expiry Tracker OTP",
            "htmlContent": f"""
                <h2>Document Expiry Tracker</h2>
                <p>Your OTP is:</p>
                <h1>{otp}</h1>
                <p>This OTP is valid for 10 minutes.</p>
                <p>If you did not request registration, you can ignore this email.</p>
            """
        }

        response = requests.post(
            url,
            headers=headers,
            json=data,
            timeout=20
        )
        print( "BREVO STATUS:", response.status_code)
        print("BREVO RESPONSE:", response.text)
        print("Brevo response:", response.status_code, response.text)

        if response.status_code in (200, 201):
            return True

        return False

    except Exception as exc:
        print("OTP email error:", exc)
        return False


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or len(password) < 6:
            flash("Enter all details. Password must be at least 6 characters.", "danger")
            return render_template("register.html")

        db = get_db()
        try:
            with db.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE email=%s", (email,))
                if cur.fetchone():
                    flash("An account with this email already exists.", "warning")
                    return render_template("register.html")

                otp = f"{random.randint(0, 999999):06d}"
                otp_hash = generate_password_hash(otp)
                expires_at = datetime.now() + timedelta(minutes=10)

                # Remove old pending OTPs for this email.
                cur.execute("DELETE FROM email_otps WHERE email=%s", (email,))
                cur.execute("""
                    INSERT INTO email_otps
                    (name, email, password_hash, otp_hash, expires_at)
                    VALUES (%s,%s,%s,%s,%s)
                """, (
                    name, email, generate_password_hash(password),
                    otp_hash, expires_at
                ))
                db.commit()

            if send_otp_email(email, otp):
                session["pending_registration_email"] = email
                flash("OTP sent to your email. It is valid for 10 minutes.", "success")
                return redirect(url_for("verify_otp"))

            # If email could not be sent, remove pending registration.
            db2 = get_db()
            try:
                with db2.cursor() as cur:
                    cur.execute("DELETE FROM email_otps WHERE email=%s", (email,))
                db2.commit()
            finally:
                db2.close()

            flash("Could not send OTP. Check your SMTP settings in .env.", "danger")
        finally:
            db.close()

    return render_template("register.html")


@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    email = session.get("pending_registration_email")
    if not email:
        return redirect(url_for("register"))

    if request.method == "POST":
        otp = request.form.get("otp", "").strip()

        db = get_db()
        try:
            with db.cursor() as cur:
                cur.execute("""
                    SELECT * FROM email_otps
                    WHERE email=%s
                    ORDER BY id DESC
                    LIMIT 1
                """, (email,))
                pending = cur.fetchone()

                if not pending:
                    flash("No pending OTP found. Please register again.", "danger")
                    return redirect(url_for("register"))

                if datetime.now() > pending["expires_at"]:
                    cur.execute("DELETE FROM email_otps WHERE id=%s", (pending["id"],))
                    flash("OTP expired. Please register again.", "warning")
                    return redirect(url_for("register"))

                if not check_password_hash(pending["otp_hash"], otp):
                    flash("Invalid OTP. Please try again.", "danger")
                    return render_template("verify_otp.html", email=email)

                cur.execute("SELECT id FROM users WHERE email=%s", (email,))
                if cur.fetchone():
                    cur.execute("DELETE FROM email_otps WHERE id=%s", (pending["id"],))
                    flash("An account with this email already exists.", "warning")
                    return redirect(url_for("login"))

                cur.execute("""
                    INSERT INTO users (name, email, password_hash, email_verified)
                    VALUES (%s, %s, %s, %s)
                """, (
                    pending["name"],
                    pending["email"],
                    pending["password_hash"],
                    True
                ))

                cur.execute(
                    "DELETE FROM email_otps WHERE id=%s",
                    (pending["id"],)
                )

                db.commit()

            session.pop("pending_registration_email", None)
            flash("Email verified and registration completed. Please login.", "success")
            return redirect(url_for("login"))
        finally:
            db.close()

    return render_template("verify_otp.html", email=email)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        db = get_db()
        try:
            with db.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE email=%s", (email,))
                user = cur.fetchone()
        finally:
            db.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("""
                SELECT * FROM documents
                WHERE user_id=%s
                ORDER BY expiry_date ASC
            """, (session["user_id"],))
            documents = cur.fetchall()

            total = len(documents)
            expired = sum(1 for d in documents if document_status(d["expiry_date"]) == "Expired")
            critical = sum(1 for d in documents if document_status(d["expiry_date"]) == "Critical")
            upcoming = sum(1 for d in documents if document_status(d["expiry_date"]) == "Expiring Soon")
            renewed = sum(1 for d in documents if d["renewal_status"] == "Renewed")

            expiring_docs = [
                d for d in documents
                if d["expiry_date"] >= date.today()
                and days_left(d["expiry_date"]) <= 30
            ][:5]
    finally:
        db.close()

    return render_template(
        "dashboard.html",
        documents=documents,
        total=total,
        expired=expired,
        critical=critical,
        upcoming=upcoming,
        renewed=renewed,
        expiring_docs=expiring_docs
    )


@app.route("/documents")
@login_required
def documents():
    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip()
    status = request.args.get("status", "").strip()

    db = get_db()
    try:
        with db.cursor() as cur:
            query = "SELECT * FROM documents WHERE user_id=%s"
            params = [session["user_id"]]

            if search:
                query += " AND (document_name ILIKE %s OR category ILIKE %s)"
                params += [f"%{search}%", f"%{search}%"]

            if category:
                query += " AND category=%s"
                params.append(category)

            query += " ORDER BY expiry_date ASC"
            cur.execute(query, params)
            all_docs = cur.fetchall()

            if status:
                all_docs = [d for d in all_docs if document_status(d["expiry_date"]) == status]
    finally:
        db.close()

    return render_template("documents.html", documents=all_docs, search=search, category=category, status=status)


@app.route("/documents/add", methods=["GET", "POST"])
@login_required
def add_document():
    if request.method == "POST":
        name = request.form.get("document_name", "").strip()
        category = request.form.get("category", "").strip()
        issue_date = request.form.get("issue_date", "")
        expiry_date = request.form.get("expiry_date", "")
        reminder_days = request.form.get("reminder_days", "30")
        file = request.files.get("file")

        if not name or not category or not issue_date or not expiry_date:
            flash("Please fill all required document details.", "danger")
            return render_template("add_document.html")

        try:
            reminder_days = int(reminder_days)
            issue_obj = datetime.strptime(issue_date, "%Y-%m-%d").date()
            expiry_obj = datetime.strptime(expiry_date, "%Y-%m-%d").date()
            if expiry_obj < issue_obj:
                raise ValueError
        except ValueError:
            flash("Please enter valid dates and reminder days.", "danger")
            return render_template("add_document.html")

        filename = None
        if file and file.filename:
            if not allowed_file(file.filename):
                flash("Only PDF, JPG, JPEG, PNG and WEBP files are allowed.", "danger")
                return render_template("add_document.html")

            safe = secure_filename(file.filename)
            filename = f"{session['user_id']}_{int(datetime.now().timestamp())}_{safe}"
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

        db = get_db()
        try:
            with db.cursor() as cur:
                cur.execute("""
                    INSERT INTO documents
                    (user_id, document_name, category, issue_date, expiry_date,
                     reminder_days, renewal_status, file_name)
                    VALUES (%s,%s,%s,%s,%s,%s,'Pending',%s)
                """, (
                    session["user_id"], name, category, issue_date, expiry_date,
                    reminder_days, filename
                ))

            db.commit()
        finally:
            db.close()

        flash("Document added successfully.", "success")
        return redirect(url_for("documents"))

    return render_template("add_document.html")


@app.route("/documents/<int:doc_id>/renew", methods=["POST"])
@login_required
def renew_document(doc_id):
    new_expiry = request.form.get("new_expiry_date", "")
    try:
        new_expiry_obj = datetime.strptime(new_expiry, "%Y-%m-%d").date()
    except ValueError:
        flash("Invalid renewal date.", "danger")
        return redirect(url_for("documents"))

    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("""
                UPDATE documents
                SET expiry_date=%s, renewal_status='Renewed', updated_at=NOW()
                WHERE id=%s AND user_id=%s
            """, (new_expiry_obj, doc_id, session["user_id"]))

        db.commit()
    finally:
        db.close()

    flash("Document renewed successfully.", "success")
    return redirect(url_for("documents"))


@app.route("/documents/<int:doc_id>/delete", methods=["POST"])
@login_required
def delete_document(doc_id):
    db = get_db()
    filename = None
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT file_name FROM documents WHERE id=%s AND user_id=%s",
                (doc_id, session["user_id"])
            )
            doc = cur.fetchone()
            if doc:
                filename = doc["file_name"]
                cur.execute(
                    "DELETE FROM documents WHERE id=%s AND user_id=%s",
                    (doc_id, session["user_id"])
                )

        db.commit()
    finally:
        db.close()

    if filename:
        path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        if os.path.exists(path):
            os.remove(path)

    flash("Document deleted.", "success")
    return redirect(url_for("documents"))


@app.route("/uploads/<filename>")
@login_required
def uploaded_file(filename):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("""
                SELECT id FROM documents
                WHERE user_id=%s AND file_name=%s
            """, (session["user_id"], filename))
            if not cur.fetchone():
                return "Unauthorized", 403
    finally:
        db.close()

    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000)),
        debug=False
    )