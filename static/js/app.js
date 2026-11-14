function enableNotifications() {
    if (!("Notification" in window)) {
        alert("Browser notifications are not supported by this browser.");
        return;
    }
    Notification.requestPermission().then(permission => {
        if (permission === "granted") {
            new Notification("Document Expiry Tracker", {
                body: "Browser expiry alerts are enabled."
            });
        }
    });
}

document.addEventListener("DOMContentLoaded", () => {
    const alerts = document.querySelectorAll(".alert");
    setTimeout(() => alerts.forEach(a => a.classList.add("hide")), 4500);
});
