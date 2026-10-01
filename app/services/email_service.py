"""
Email Service for Job Search Operating Agent.
Provides:
  - Direct in-app email dispatching via standard SMTP (TLS / SSL / STARTTLS)
  - Connection testing and credential validation
  - Smart corporate email address inference (e.g. Lightspeed, CRA, etc.)
  - Mailto fallback link generation
  - Local configuration persistence for SMTP credentials
"""
from __future__ import annotations

import json
import os
import re
import smtplib
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path
from typing import Any, Optional

import importlib
import app.config as config_module
try:
    importlib.reload(config_module)
    settings = config_module.settings
except Exception:
    from app.config import settings

EMAIL_CONFIG_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "email_config.json"


@dataclass
class EmailResult:
    success: bool
    message: str
    simulated: bool = False
    details: Optional[dict[str, Any]] = None


def load_saved_email_config() -> dict[str, Any]:
    """Load saved email settings from local storage or environment."""
    config = {
        "smtp_host": getattr(settings, "smtp_host", "") or os.getenv("SMTP_HOST", ""),
        "smtp_port": getattr(settings, "smtp_port", 587) or int(os.getenv("SMTP_PORT", 587)),
        "smtp_username": getattr(settings, "smtp_username", "") or os.getenv("SMTP_USER", os.getenv("SMTP_USERNAME", "")),
        "smtp_password": getattr(settings, "smtp_password", "") or os.getenv("SMTP_PASSWORD", os.getenv("SMTP_PASS", "")),
        "smtp_sender_email": getattr(settings, "smtp_sender_email", "") or os.getenv("SMTP_SENDER_EMAIL", os.getenv("SENDER_EMAIL", "")),
        "smtp_sender_name": getattr(settings, "smtp_sender_name", "Elena Shchetinina") or os.getenv("SMTP_SENDER_NAME", "Elena Shchetinina"),
        "smtp_use_tls": getattr(settings, "smtp_use_tls", True),
        "smtp_use_ssl": getattr(settings, "smtp_use_ssl", False),
    }

    if EMAIL_CONFIG_FILE.exists():
        try:
            stored = json.loads(EMAIL_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                for k, v in stored.items():
                    if v not in (None, ""):
                        config[k] = v
        except Exception:
            pass

    return config


def save_email_config(config_data: dict[str, Any]) -> None:
    """Save email configuration securely to local data file and settings."""
    EMAIL_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if EMAIL_CONFIG_FILE.exists():
        try:
            existing = json.loads(EMAIL_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    existing.update(config_data)
    EMAIL_CONFIG_FILE.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    # Update runtime settings object if keys match
    for k, v in config_data.items():
        if hasattr(settings, k):
            setattr(settings, k, v)


def is_valid_email(email_str: str) -> bool:
    """Basic validation for RFC 5322 email string."""
    if not email_str or not isinstance(email_str, str):
        return False
    email_str = email_str.strip()
    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    return bool(re.match(pattern, email_str))


def suggest_email_for_contact(name: str, company: str) -> str:
    """
    Intelligently infer likely work email address based on company domain patterns.
    """
    clean_name = name.strip()
    clean_co = company.strip().lower()

    parts = [p.lower() for p in re.sub(r"[^a-zA-Z\s]", "", clean_name).split() if p]
    if not parts:
        return ""

    first = parts[0]
    last = parts[-1] if len(parts) > 1 else ""

    # Known company domains
    domain_map = {
        "lightspeed": "lightspeedhq.com",
        "lightspeed commerce": "lightspeedhq.com",
        "lightspeed pos": "lightspeedhq.com",
        "charles river associates": "crai.com",
        "rwe": "rwe.com",
        "apply": "apply.com",
        "shopify": "shopify.com",
        "rbc": "rbc.com",
        "td": "td.com",
        "scotiabank": "scotiabank.com",
        "bmo": "bmo.com",
        "cibc": "cibc.com",
    }

    target_domain = None
    for co_key, dom in domain_map.items():
        if co_key in clean_co:
            target_domain = dom
            break

    if not target_domain:
        # Fallback to sanitized company name
        co_slug = re.sub(r"\b(corporation|corporate|corp|incorporated|inc|limited|ltd|company|technologies|solutions|group|holdings)\b", "", clean_co)
        co_slug = re.sub(r"[^a-z0-9]", "", co_slug)
        if co_slug:
            target_domain = f"{co_slug}.com"
        else:
            target_domain = "company.com"

    if last:
        return f"{first}.{last}@{target_domain}"
    return f"{first}@{target_domain}"


def generate_email_subject(job_title: str, candidate_name: str = "Elena Shchetinina", company: str = "") -> str:
    """Generate a clean, high-impact subject line for outreach."""
    title_clean = job_title.strip()
    cand_clean = candidate_name.strip()
    if company:
        return f"{title_clean} — Introduction & Application ({cand_clean})"
    return f"{title_clean} | Application & Introduction — {cand_clean}"


def generate_mailto_link(to_email: str, subject: str, body: str) -> str:
    """Generate a RFC 6068 mailto: URI pre-populated with recipient, subject, and body."""
    params = {
        "subject": subject or "",
        "body": body or "",
    }
    encoded = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return f"mailto:{to_email.strip()}?{encoded}"


def test_smtp_connection(
    host: str,
    port: int,
    username: str,
    password: str,
    use_tls: bool = True,
    use_ssl: bool = False,
    timeout: int = 10,
) -> tuple[bool, str]:
    """Test SMTP connection, TLS handshake, and authentication."""
    if not host:
        return False, "SMTP Host is missing."

    clean_host = host.strip()
    clean_user = username.strip() if username else ""
    clean_pass = password.strip() if password else ""
    is_gmail = "gmail" in clean_host.lower()

    # Automatically enforce TLS for port 587 or Gmail
    effective_tls = use_tls or is_gmail or (port == 587)
    effective_ssl = use_ssl or (port == 465)

    try:
        if effective_ssl:
            server = smtplib.SMTP_SSL(clean_host, port, timeout=timeout)
        else:
            server = smtplib.SMTP(clean_host, port, timeout=timeout)

        # Explicitly pass 'localhost' to prevent macOS reverse DNS IPv6 timeout
        server.ehlo("localhost")
        if effective_tls and not effective_ssl:
            server.starttls()
            server.ehlo("localhost")

        if clean_user and clean_pass:
            try:
                server.login(clean_user, clean_pass)
            except Exception as first_err:
                # If password contains dashes or spaces, attempt stripped version
                stripped_pass = clean_pass.replace(" ", "").replace("-", "")
                if stripped_pass != clean_pass:
                    try:
                        server.quit()
                    except Exception:
                        pass
                    if effective_ssl:
                        server = smtplib.SMTP_SSL(clean_host, port, timeout=timeout)
                    else:
                        server = smtplib.SMTP(clean_host, port, timeout=timeout)
                    server.ehlo("localhost")
                    if effective_tls and not effective_ssl:
                        server.starttls()
                        server.ehlo("localhost")
                    server.login(clean_user, stripped_pass)
                else:
                    raise first_err

        server.quit()
        return True, f"Successfully connected and authenticated with {clean_host}:{port}!"
    except smtplib.SMTPAuthenticationError as e:
        err_str = str(e)
        if "534" in err_str or "Application-specific password" in err_str or "InvalidSecondFactor" in err_str:
            return False, "Gmail requires an official 16-letter App Password. Please generate one at https://myaccount.google.com/apppasswords and paste it here."
        return False, f"SMTP Authentication failed (check email/app password): {e}"
    except smtplib.SMTPConnectError as e:
        return False, f"Failed to connect to SMTP server {clean_host}:{port}: {e}"
    except Exception as e:
        err_str = str(e)
        if is_gmail and ("Application-specific password" in err_str or "534" in err_str or "InvalidSecondFactor" in err_str or "Connection unexpectedly closed" in err_str):
            return False, "Gmail authentication rejected. Google accounts with 2-Step Verification require an official 16-character App Password (go to https://myaccount.google.com/apppasswords)."
        return False, f"SMTP Connection error: {e}"



def send_email(
    to_email: str,
    subject: str,
    body: str,
    from_email: Optional[str] = None,
    from_name: Optional[str] = None,
    smtp_config: Optional[dict[str, Any]] = None,
    simulated: bool = False,
    is_approved: bool = True,
) -> EmailResult:
    """
    Send an email directly from the application.
    Enforces that outreach must be approved prior to dispatch.
    """
    if not is_approved:
        return EmailResult(
            success=False,
            message="Email dispatch blocked: Recipient outreach has not been approved. Approval is required before sending.",
        )

    to_email = (to_email or "").strip()
    if not is_valid_email(to_email):
        return EmailResult(
            success=False,
            message=f"Invalid recipient email address: '{to_email}'",
        )

    if not subject.strip():
        return EmailResult(
            success=False,
            message="Email subject cannot be empty.",
        )

    if not body.strip():
        return EmailResult(
            success=False,
            message="Email body cannot be empty.",
        )

    # Resolve configuration
    cfg = load_saved_email_config()
    if smtp_config:
        cfg.update(smtp_config)

    sender_email = (from_email or cfg.get("smtp_sender_email") or cfg.get("smtp_username") or "").strip()
    sender_name = (from_name or cfg.get("smtp_sender_name") or "Elena Shchetinina").strip()

    if simulated:
        # Simulated mode: verifies payload structure and returns success
        return EmailResult(
            success=True,
            message=f"Simulated email successfully prepared and dispatched to {to_email}",
            simulated=True,
            details={
                "to": to_email,
                "from": f"{sender_name} <{sender_email}>" if sender_email else sender_name,
                "subject": subject,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    # Live SMTP Dispatch
    host = cfg.get("smtp_host", "").strip()
    port = int(cfg.get("smtp_port") or 587)
    username = cfg.get("smtp_username", "").strip()
    password = cfg.get("smtp_password", "").strip()
    use_tls = cfg.get("smtp_use_tls", True)
    use_ssl = cfg.get("smtp_use_ssl", False)

    if not host or not username:
        return EmailResult(
            success=False,
            message=(
                "SMTP configuration is incomplete. Please configure your SMTP Host, Username/Email, "
                "and App Password in the SMTP Settings section."
            ),
        )

    if not sender_email:
        sender_email = username

    # Build Email Message
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{sender_name} <{sender_email}>" if sender_name else sender_email
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(body, charset="utf-8")

    clean_user = username.strip() if username else ""
    clean_pass = password.strip() if password else ""
    is_gmail = "gmail" in host.lower()
    effective_tls = use_tls or is_gmail or (port == 587)
    effective_ssl = use_ssl or (port == 465)

    try:
        if effective_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            server = smtplib.SMTP(host, port, timeout=15)

        server.ehlo("localhost")
        if effective_tls and not effective_ssl:
            server.starttls()
            server.ehlo("localhost")

        if clean_user and clean_pass:
            try:
                server.login(clean_user, clean_pass)
            except Exception as first_err:
                stripped_pass = clean_pass.replace(" ", "").replace("-", "")
                if stripped_pass != clean_pass:
                    try:
                        server.quit()
                    except Exception:
                        pass
                    if effective_ssl:
                        server = smtplib.SMTP_SSL(host, port, timeout=15)
                    else:
                        server = smtplib.SMTP(host, port, timeout=15)
                    server.ehlo("localhost")
                    if effective_tls and not effective_ssl:
                        server.starttls()
                        server.ehlo("localhost")
                    server.login(clean_user, stripped_pass)
                else:
                    raise first_err

        server.send_message(msg)
        server.quit()

        return EmailResult(
            success=True,
            message=f"Email successfully delivered to {to_email} via {host}:{port}!",
            simulated=False,
            details={
                "to": to_email,
                "from": f"{sender_name} <{sender_email}>",
                "subject": subject,
                "host": host,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
    except smtplib.SMTPAuthenticationError as e:
        return EmailResult(
            success=False,
            message=f"Authentication error with {host}: Check your username and App Password. ({e})",
        )
    except smtplib.SMTPConnectError as e:
        return EmailResult(
            success=False,
            message=f"Connection error: Could not reach {host}:{port}. ({e})",
        )
    except Exception as e:
        return EmailResult(
            success=False,
            message=f"Failed to send email via SMTP: {e}",
        )


def send_outreach_email(
    outreach: Any,
    to_email: Optional[str] = None,
    subject: Optional[str] = None,
    body: Optional[str] = None,
    from_email: Optional[str] = None,
    from_name: Optional[str] = None,
    smtp_config: Optional[dict[str, Any]] = None,
    simulated: bool = False,
) -> EmailResult:
    """
    Send an outreach email with strict human-in-the-loop approval verification.
    Guarantees that no email can be sent to non-approved recipients.
    """
    status_val = getattr(outreach, "approval_status", "")
    if hasattr(status_val, "value"):
        status_val = status_val.value

    if status_val != "approved":
        person_name = getattr(outreach, "person_name", "recipient") or "recipient"
        return EmailResult(
            success=False,
            message=(
                f"Email dispatch rejected: Outreach record for '{person_name}' is in '{status_val}' status. "
                "The message must be approved before an email can be sent."
            ),
        )

    target_email = (to_email or getattr(outreach, "recipient_email", None) or "").strip()
    target_subject = (subject or getattr(outreach, "subject", None) or "").strip()
    target_body = (body or getattr(outreach, "draft", None) or "").strip()

    return send_email(
        to_email=target_email,
        subject=target_subject,
        body=target_body,
        from_email=from_email,
        from_name=from_name,
        smtp_config=smtp_config,
        simulated=simulated,
        is_approved=True,
    )
