"""
Email sender — sends personalised outreach emails to recruiters via Gmail SMTP.

Each email:
  - Personalized subject line with job title and company
  - Cover letter as email body
  - Resume PDF attached
  - Plain text (not HTML) for better deliverability
"""

import logging
import mimetypes
import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from src.db import tracker

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def send_recruiter_email(
    to_email: str,
    job: dict,
    cover_letter: str,
    config: dict,
) -> bool:
    """
    Send a personalised email to a recruiter.

    Args:
        to_email: Recruiter's email address
        job: dict with title, company, url, id
        cover_letter: personalised cover letter text
        config: loaded settings.yaml

    Returns:
        True if sent successfully, False otherwise
    """
    from_email = os.getenv("EMAIL_ADDRESS", "")
    app_password = os.getenv("EMAIL_APP_PASSWORD", "")

    if not from_email or not app_password:
        logger.error("EMAIL_ADDRESS or EMAIL_APP_PASSWORD not set in .env")
        return False

    personal = config.get("personal", {})
    first_name = personal.get("first_name", "")
    last_name = personal.get("last_name", "")
    full_name = f"{first_name} {last_name}".strip()

    # Build subject
    subject_template = config.get("email_outreach", {}).get(
        "subject_template",
        "Application for {job_title} at {company} — {first_name} {last_name}"
    )
    subject = subject_template.format(
        job_title=job.get("title", ""),
        company=job.get("company", ""),
        first_name=first_name,
        last_name=last_name,
    )

    # Build body
    body = _build_email_body(cover_letter, job, personal)

    # Construct MIME message
    msg = MIMEMultipart()
    msg["From"] = f"{full_name} <{from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = from_email

    msg.attach(MIMEText(body, "plain", "utf-8"))

    # Attach resume PDF
    resume_path = Path(config.get("resume_path", "resume/resume.pdf")).resolve()
    if resume_path.exists():
        _attach_file(msg, resume_path)
    else:
        logger.warning("Resume not found at %s — sending without attachment", resume_path)

    # Send via Gmail SMTP
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(from_email, app_password)
            server.sendmail(from_email, to_email, msg.as_string())

        logger.info("Email sent to %s for %s @ %s", to_email, job.get("title"), job.get("company"))
        tracker.log_email(
            job_id=job["id"],
            to_email=to_email,
            subject=subject,
            success=True,
        )
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error("Gmail SMTP auth failed — check EMAIL_APP_PASSWORD in .env")
        _log_failed(job["id"], to_email, subject, "SMTP auth error")
        return False

    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to_email, exc)
        _log_failed(job["id"], to_email, subject, str(exc))
        return False


def send_follow_up_email(
    to_email: str,
    job: dict,
    config: dict,
) -> bool:
    """Send a brief follow-up email after no response."""
    from_email = os.getenv("EMAIL_ADDRESS", "")
    app_password = os.getenv("EMAIL_APP_PASSWORD", "")
    if not from_email or not app_password:
        return False

    personal = config.get("personal", {})
    first_name = personal.get("first_name", "")
    last_name = personal.get("last_name", "")

    subject = f"Following up — {job.get('title', '')} at {job.get('company', '')}"
    body = (
        f"Dear Hiring Team,\n\n"
        f"I wanted to follow up on my application for the {job.get('title', '')} position at "
        f"{job.get('company', '')} submitted last week. I remain very interested in this opportunity "
        f"and would welcome the chance to discuss further.\n\n"
        f"Thank you for your time.\n\n"
        f"Best regards,\n{first_name} {last_name}"
    )

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = f"{first_name} {last_name} <{from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(from_email, app_password)
            server.sendmail(from_email, to_email, msg.as_string())
        logger.info("Follow-up sent to %s for %s @ %s", to_email, job.get("title"), job.get("company"))
        return True
    except Exception as exc:
        logger.error("Follow-up email failed: %s", exc)
        return False


def _build_email_body(cover_letter: str, job: dict, personal: dict) -> str:
    linkedin_url = personal.get("linkedin_url", "")
    portfolio_url = personal.get("portfolio_url", "")
    phone = personal.get("phone", "")
    email = os.getenv("EMAIL_ADDRESS", "")

    signature_parts = [cover_letter.strip(), "\n"]
    if linkedin_url:
        signature_parts.append(f"LinkedIn: {linkedin_url}")
    if portfolio_url:
        signature_parts.append(f"Portfolio: {portfolio_url}")
    if phone:
        signature_parts.append(f"Phone: {phone}")
    if email:
        signature_parts.append(f"Email: {email}")

    return "\n".join(signature_parts)


def _attach_file(msg: MIMEMultipart, path: Path) -> None:
    with open(path, "rb") as f:
        part = MIMEApplication(f.read(), Name=path.name)
    part["Content-Disposition"] = f'attachment; filename="{path.name}"'
    msg.attach(part)


def _log_failed(job_id: str, to_email: str, subject: str, error: str) -> None:
    tracker.log_email(
        job_id=job_id,
        to_email=to_email,
        subject=subject,
        success=False,
        error_msg=error,
    )
