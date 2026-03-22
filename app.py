# ─────────────────────────────────────────────────────────────────
#  app.py  —  Flask Email Sender (Bulk Email + Scheduling)
#
#  Features:
#    1. Send email to one OR multiple recipients (comma-separated)
#    2. Schedule an email to be sent at a future date/time
#    3. Simple single-page web form
#
#  Libraries used:
#    - Flask      → web framework (routes, templates)
#    - smtplib    → Python built-in, sends emails via SMTP
#    - threading  → Python built-in, runs scheduler in background
#    - datetime   → Python built-in, handles date/time logic
# ─────────────────────────────────────────────────────────────────

import smtplib
import ssl
import threading                      # lets us run the scheduler WITHOUT freezing the app
from datetime import datetime         # for comparing times
from time import sleep                # for waiting until scheduled time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import Flask, render_template, request

import config                         # our Gmail credentials from config.py

# ── Create the Flask app ──────────────────────────────────────────
app = Flask(__name__)


# ══════════════════════════════════════════════════════════════════
#  FUNCTION 1 — parse_recipients()
#
#  Converts the raw "To" text field into a clean Python list.
#
#  INPUT  : "alice@gmail.com,  bob@gmail.com , carol@gmail.com"
#  OUTPUT : ["alice@gmail.com", "bob@gmail.com", "carol@gmail.com"]
# ══════════════════════════════════════════════════════════════════

def parse_recipients(raw_text):
    emails = []
    for part in raw_text.split(","):       # split by comma
        email = part.strip()               # remove extra spaces
        if email:                          # skip blank entries
            emails.append(email)
    return emails


# ══════════════════════════════════════════════════════════════════
#  FUNCTION 2 — send_email()
#
#  Connects to Gmail SMTP and sends the email RIGHT NOW.
#
#  Parameters:
#    to_emails  (list) — one or more recipient addresses
#    subject    (str)  — email subject line
#    body       (str)  — email body text
#
#  Returns:
#    (True,  "success message")  ← if sent OK
#    (False, "error message")    ← if something went wrong
# ══════════════════════════════════════════════════════════════════

def send_email(to_emails, subject, body):

    # Build the email message object
    msg = MIMEMultipart()
    msg["From"]    = config.SENDER_EMAIL
    msg["To"]      = ", ".join(to_emails)   # "a@x.com, b@x.com"
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))     # attach the plain-text body

    try:
        context = ssl.create_default_context()   # secure TLS context

        # Open connection to Gmail's SMTP server
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
            server.ehlo()                        # say hello to the server
            server.starttls(context=context)     # upgrade to encrypted connection
            server.ehlo()
            server.login(config.SENDER_EMAIL, config.APP_PASSWORD)
            server.sendmail(config.SENDER_EMAIL, to_emails, msg.as_string())

        return True, f"Email sent to {len(to_emails)} recipient(s) successfully!"

    except smtplib.SMTPAuthenticationError:
        return False, "Login failed — check your email and App Password in config.py."

    except smtplib.SMTPConnectError:
        return False, "Could not connect to Gmail. Check your internet connection."

    except smtplib.SMTPException as e:
        return False, f"SMTP error: {str(e)}"

    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


# ══════════════════════════════════════════════════════════════════
#  FUNCTION 3 — schedule_email()
#
#  Waits until the right time, then calls send_email().
#  Runs in a BACKGROUND THREAD so the website stays responsive.
#
#  How threading works here (simple explanation):
#    - Normal code runs line by line (blocking)
#    - threading.Thread runs a function in parallel (non-blocking)
#    - So the user sees "Scheduled!" instantly, while the thread
#      waits quietly in the background and sends when it's time.
#
#  Parameters:
#    send_at    (datetime) — when to send
#    to_emails  (list)     — recipients
#    subject    (str)
#    body       (str)
# ══════════════════════════════════════════════════════════════════

def schedule_email(send_at, to_emails, subject, body):

    def run():
        # How many seconds until the scheduled time?
        wait_seconds = (send_at - datetime.now()).total_seconds()

        if wait_seconds > 0:
            print(f"[Scheduler] Waiting {int(wait_seconds)} seconds to send email...")
            sleep(wait_seconds)           # sleep until it's time

        # Time's up — send the email now
        print(f"[Scheduler] Sending now to: {to_emails}")
        ok, msg = send_email(to_emails, subject, body)
        print(f"[Scheduler] Result → {msg}")

    # daemon=True means: if the app is closed, this thread stops too
    t = threading.Thread(target=run, daemon=True)
    t.start()
    print(f"[Scheduler] Background thread started for: {send_at}")


# ══════════════════════════════════════════════════════════════════
#  FLASK ROUTE — index()
#
#  The only route in this app: "/"
#
#  GET  request → user just opened the page → show empty form
#  POST request → user clicked "Send" → process the form data
# ══════════════════════════════════════════════════════════════════

@app.route("/", methods=["GET", "POST"])
def index():

    # These three variables are passed to the HTML template
    success   = None    # True → green alert,  False → red alert,  None → no alert
    message   = None    # the text shown in the alert box
    scheduled = False   # True → show "scheduled" style alert instead of "sent"

    if request.method == "POST":

        # ── Read the 4 form fields ─────────────────────────────────
        raw_recipients = request.form.get("recipients",   "").strip()
        subject        = request.form.get("subject",      "").strip()
        body           = request.form.get("body",         "").strip()
        schedule_time  = request.form.get("schedule_time","").strip()
        # schedule_time will be like "2025-06-15T09:30" or "" if not filled

        # ── Validate: all required fields must be filled ───────────
        if not raw_recipients or not subject or not body:
            success = False
            message = "Please fill in all fields — Recipients, Subject, and Message."

        else:
            # ── Parse the comma-separated emails into a list ───────
            to_emails = parse_recipients(raw_recipients)

            if len(to_emails) == 0:
                success = False
                message = "No valid email addresses found. Separate multiple emails with commas."

            # ── CASE A: User gave a schedule time → schedule it ────
            elif schedule_time:
                try:
                    # Convert string "2025-06-15T09:30" to Python datetime object
                    send_at = datetime.strptime(schedule_time, "%Y-%m-%dT%H:%M")

                    # Scheduled time must be in the future
                    if send_at <= datetime.now():
                        success = False
                        message = "Please choose a future date and time."
                    else:
                        # Hand off to the background scheduler
                        schedule_email(send_at, to_emails, subject, body)
                        success   = True
                        scheduled = True   # flag for the template to show clock icon
                        message   = (
                            f"Scheduled for {send_at.strftime('%d %b %Y at %I:%M %p')} "
                            f"— {len(to_emails)} recipient(s). "
                            f"Keep this app running until then!"
                        )

                except ValueError:
                    success = False
                    message = "Invalid date/time. Please use the date picker in the form."

            # ── CASE B: No schedule time → send immediately ────────
            else:
                success, message = send_email(to_emails, subject, body)

    # Pass variables to the HTML template and render the page
    return render_template("index.html",
                           success=success,
                           message=message,
                           scheduled=scheduled)


# ── Start the Flask development server ───────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  AutoMailer is running!")
    print("  Open: http://localhost:5000")
    print("=" * 50)
    app.run(debug=True)