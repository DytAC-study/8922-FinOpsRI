from email_utils import send_email

send_email(
    subject="🔔 Test from Gmail Mode",
    html_body="<h2>This is a test email via Gmail</h2><p>✅ Gmail mode test successful.</p>",
    recipient="你的真实邮箱@example.com"
)
