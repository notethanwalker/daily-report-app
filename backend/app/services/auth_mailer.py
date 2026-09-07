from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

from sqlalchemy.orm import Session

from ..auth_models import AuthAccount
from .auth_security import decrypt_text


def mail_configured() -> bool:
    return bool(os.getenv("AUTH_SMTP_APP_PASSWORD", "").strip())


def _send(to_email: str, subject: str, body: str, from_email: str) -> bool:
    password = os.getenv("AUTH_SMTP_APP_PASSWORD", "").strip()
    if not password:
        return False
    host = os.getenv("AUTH_SMTP_HOST", "smtp.gmail.com").strip() or "smtp.gmail.com"
    port = int(os.getenv("AUTH_SMTP_PORT", "465") or 465)
    message = EmailMessage()
    message["From"] = from_email
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=context, timeout=15) as server:
            server.login(from_email, password)
            server.send_message(message)
        return True
    except Exception:
        # Authentication addresses/passwords are intentionally never written to logs.
        return False


def _owner(db: Session) -> AuthAccount | None:
    return db.query(AuthAccount).filter(
        AuthAccount.role == "owner", AuthAccount.status == "approved", AuthAccount.enabled.is_(True)
    ).order_by(AuthAccount.created_at.asc()).first()


def notify_owner_registration(db: Session, requester: AuthAccount) -> bool:
    owner = _owner(db)
    if not owner:
        return False
    owner_email = decrypt_text(owner.email_ciphertext)
    requester_email = decrypt_text(requester.email_ciphertext)
    if not owner_email or not requester_email:
        return False
    body = (
        "A new Daily Report account is awaiting approval.\n\n"
        f"Requested email: {requester_email}\n"
        f"Account ID: {requester.id}\n\n"
        "Open Daily Report, sign in as the administrator, then open Settings → Pending account approvals "
        "to approve or reject this request. No password or password hash is included in this email."
    )
    return _send(owner_email, "Daily Report account approval requested", body, owner_email)


def notify_user_decision(db: Session, account: AuthAccount, approved: bool) -> bool:
    owner = _owner(db)
    if not owner:
        return False
    owner_email = decrypt_text(owner.email_ciphertext)
    user_email = decrypt_text(account.email_ciphertext)
    if not owner_email or not user_email:
        return False
    if approved:
        subject = "Daily Report account approved"
        body = "Your Daily Report account has been approved. You can now sign in with the email and password you created."
    else:
        subject = "Daily Report account request declined"
        body = "Your Daily Report account request was declined by the administrator."
    return _send(user_email, subject, body, owner_email)
