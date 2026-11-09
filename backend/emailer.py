"""
Email sending.

Two ways to send, picked from env variables:
  1. BREVO_API_KEY  -> Brevo HTTP API (works on Render free tier, which blocks SMTP ports)
  2. SMTP_USER/SMTP_PASSWORD -> normal SMTP (e.g. Gmail with an app password), good for local runs
If neither is set, the email is only printed + logged ("simulated") so the app still works in a demo.
"""

import os
import smtplib
from email.mime.text import MIMEText

import requests

SENDER_NAME = "Evo11ve AI Skills Assistant"


def _sender_email() -> str:
    return os.getenv("SENDER_EMAIL") or os.getenv("SMTP_USER", "")


def team_email() -> str:
    # where callback / escalation / enrollment alerts go
    return os.getenv("TEAM_EMAIL") or _sender_email()


def send_email(to: str, subject: str, body: str) -> str:
    """Returns 'sent', 'simulated' or 'failed'."""
    use_brevo = bool(os.getenv("BREVO_API_KEY"))
    use_smtp = bool(os.getenv("SMTP_USER") and os.getenv("SMTP_PASSWORD"))

    if not (use_brevo or use_smtp):
        print(f"[email simulated] to={to or '(team inbox not set)'} subject={subject}\n{body}\n")
        return "simulated"
    if not to:
        return "failed"

    try:
        if use_brevo:
            _send_brevo(to, subject, body)
        else:
            _send_smtp(to, subject, body)
        return "sent"
    except Exception as e:
        print(f"[email failed] to={to}: {e}")
        return "failed"


def _send_smtp(to: str, subject: str, body: str):
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = f"{SENDER_NAME} <{_sender_email()}>"
    msg["To"] = to

    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=20) as server:
        server.starttls()
        server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        server.send_message(msg)


def _send_brevo(to: str, subject: str, body: str):
    resp = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": os.environ["BREVO_API_KEY"], "Content-Type": "application/json"},
        json={
            "sender": {"name": SENDER_NAME, "email": _sender_email()},
            "to": [{"email": to}],
            "subject": subject,
            "textContent": body,
        },
        timeout=20,
    )
    resp.raise_for_status()


# ---------- email templates for each action ----------

def build_emails(action: str, d: dict, transcript: str) -> list[tuple[str, str, str]]:
    """Returns a list of (to, subject, body) for the given action."""
    name = d.get("name") or "there"
    emails = []

    details = (
        f"Name: {d.get('name') or '-'}\n"
        f"Email: {d.get('email') or '-'}\n"
        f"Phone: {d.get('phone') or '-'}\n"
        f"Student class: {d.get('student_class') or '-'}\n"
        f"Preferred project: {d.get('project') or '-'}\n"
        f"Preferred call time: {d.get('preferred_time') or '-'}\n"
        f"Note: {d.get('note') or '-'}\n"
    )

    if action == "enrollment":
        if d.get("email"):
            emails.append((
                d["email"],
                "Your AI Skills Program enrollment request - Evo11ve",
                f"Hi {name},\n\n"
                "Thanks for your interest in Evo11ve's AI Skills Program! We have received your enrollment request.\n\n"
                f"{details}\n"
                "Program summary:\n"
                "- For students in Classes 6-12, no coding experience needed\n"
                "- 50 hours: 12 hrs live mentor sessions, 36 hrs guided project building, 2 hrs doubt clearing\n"
                "- Portfolio-ready capstone project + blockchain-backed certificate\n"
                "- 12 months of mentor support\n"
                "- Fee: Rs 9,999 per student\n\n"
                "Our team will contact you shortly to complete the registration.\n"
                "You can also register directly at https://evo11ve.ai/for-ai\n\n"
                "Regards,\nTeam Evo11ve",
            ))
        emails.append((team_email(), f"[New enrollment] {d.get('name', '')}", f"New enrollment request:\n\n{details}"))

    elif action == "callback":
        if d.get("email"):
            emails.append((
                d["email"],
                "Callback request received - Evo11ve AI Skills Program",
                f"Hi {name},\n\nWe've received your callback request. Someone from the Evo11ve team will call you "
                f"on {d.get('phone') or 'your number'}"
                f"{' around ' + d['preferred_time'] if d.get('preferred_time') else ''} within one business day.\n\n"
                "Regards,\nTeam Evo11ve",
            ))
        emails.append((team_email(), f"[Callback request] {d.get('name', '')} - {d.get('phone', '')}",
                       f"Please call back this user:\n\n{details}"))

    elif action == "escalation":
        if d.get("email"):
            emails.append((
                d["email"],
                "We've passed your query to our team - Evo11ve",
                f"Hi {name},\n\nI've passed your query to a member of the Evo11ve team. "
                "They will get back to you within one business day.\n\nRegards,\nTeam Evo11ve",
            ))
        emails.append((team_email(), f"[Escalation] {d.get('name', '')} needs a human",
                       f"A user asked to talk to a human.\n\n{details}\nConversation:\n{transcript}"))

    return emails
