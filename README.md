# Document Expiry Tracker

College Mini Project based on the submitted project proposal.

## Features
- User registration and login
- Secure password hashing
- Add and upload documents
- Document categories
- Issue date and expiry date tracking
- Smart status classification
- Dashboard for total, expiring, critical and expired documents
- Custom reminder period
- Search and status filtering
- Renewal status tracking
- Delete documents
- Browser notification support on the dashboard
- Secure per-user document access

## Technology
- Frontend: HTML, CSS, JavaScript
- Backend: Python Flask
- Database: MySQL
- Notifications: Browser notifications
- Document processing/storage: PDF and image upload handling
- Development: Visual Studio Code
- Version Control: Git/GitHub

## Setup on Windows

### 1. Install Python
Install Python 3.10+ and make sure `python` works in Command Prompt.

### 2. Install MySQL
Install MySQL Server and MySQL Workbench.

### 3. Create database
Open MySQL Workbench and run all commands from `schema.sql`.

### 4. Create virtual environment
Open Command Prompt in this project folder:

python -m venv venv
venv\Scripts\activate

### 5. Install packages

pip install -r requirements.txt

### 6. Configure database
Copy `.env.example` to `.env` and set your MySQL password.

Example:

DB_HOST=localhost
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_NAME=document_tracker

### 7. Run

python app.py

Open:
http://127.0.0.1:5000

## Smart reminder logic
- More than 30 days: Active
- 8–30 days: Expiring Soon
- 0–7 days: Critical
- Less than 0 days: Expired

The reminder_days value is stored for each document so the project can be extended to email notifications later.
