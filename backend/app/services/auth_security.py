from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..auth_models import AuthAccount, AuthSession
from ..models import UserProfile, UserWatchlistItem, WatchlistItem
from ..multiuser_models import UserAccessConfig, UserPreferences

SESSION_COOKIE="daily_report_session";SESSION_DAYS=7;PASSWORD_N=2**14;PASSWORD_R=8;PASSWORD_P=1;PASSWORD_DKLEN=32;SENTINEL="__INITIALIZED__"
EMAIL_RE=re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

def _b64e(value:bytes)->str:return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
def _b64d(value:str)->bytes:return base64.urlsafe_b64decode(value+"="*(-len(value)%4))
def _required_key(name:str)->bytes:
    raw=os.getenv(name,"").strip()
    if not raw:raise RuntimeError(f"{name} is not configured")
    key=_b64d(raw)
    if len(key)<32:raise RuntimeError(f"{name} must contain at least 32 bytes")
    return key[:32]
def normalize_email(email:str)->str:
    normalized=(email or "").strip().lower()
    if len(normalized)>320 or not EMAIL_RE.match(normalized):raise ValueError("Enter a valid email address")
    return normalized
def validate_password(password:str)->None:
    if len(password or "")<12:raise ValueError("Password must be at least 12 characters")
    if len(password)>256:raise ValueError("Password is too long")
    if not any(ch.isalpha() for ch in password) or not any(ch.isdigit() for ch in password):raise ValueError("Password must include at least one letter and one number")
def encrypt_text(value:str)->str:
    nonce=os.urandom(12);ciphertext=AESGCM(_required_key("AUTH_ENCRYPTION_KEY")).encrypt(nonce,value.encode("utf-8"),None);return _b64e(nonce+ciphertext)
def decrypt_text(value:str|None)->str|None:
    if not value:return None
    raw=_b64d(value)
    if len(raw)<29:raise ValueError("Encrypted value is invalid")
    return AESGCM(_required_key("AUTH_ENCRYPTION_KEY")).decrypt(raw[:12],raw[12:],None).decode("utf-8")
def email_lookup(email:str)->str:return hmac.new(_required_key("AUTH_LOOKUP_KEY"),normalize_email(email).encode("utf-8"),hashlib.sha256).hexdigest()
def hash_password(password:str)->str:
    validate_password(password);salt=os.urandom(16);derived=hashlib.scrypt(password.encode("utf-8"),salt=salt,n=PASSWORD_N,r=PASSWORD_R,p=PASSWORD_P,dklen=PASSWORD_DKLEN);return f"scrypt${PASSWORD_N}${PASSWORD_R}${PASSWORD_P}${_b64e(salt)}${_b64e(derived)}"
def verify_password(password:str,encoded:str)->bool:
    try:
        algorithm,n,r,p,salt_text,digest_text=encoded.split("$",5)
        if algorithm!="scrypt":return False
        expected=_b64d(digest_text);actual=hashlib.scrypt(password.encode("utf-8"),salt=_b64d(salt_text),n=int(n),r=int(r),p=int(p),dklen=len(expected));return secrets.compare_digest(actual,expected)
    except Exception:return False
def _session_digest(token:str)->str:return hmac.new(_required_key("AUTH_SESSION_PEPPER"),token.encode("utf-8"),hashlib.sha256).hexdigest()
def create_session(db:Session,user_id:str)->str:
    token=secrets.token_urlsafe(48);now=datetime.now(timezone.utc);db.add(AuthSession(token_hash=_session_digest(token),user_id=user_id,created_at=now,last_seen_at=now,expires_at=now+timedelta(days=SESSION_DAYS)));db.commit();return token
def revoke_session(db:Session,token:str|None)->None:
    if not token:return
    row=db.get(AuthSession,_session_digest(token))
    if row:db.delete(row);db.commit()
def revoke_all_sessions(db:Session,user_id:str)->None:db.query(AuthSession).filter(AuthSession.user_id==user_id).delete(synchronize_session=False);db.commit()
def account_from_session(db:Session,token:str|None)->AuthAccount|None:
    if not token:return None
    row=db.get(AuthSession,_session_digest(token))
    if not row:return None
    now=datetime.now(timezone.utc);expiry=row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expiry<=now:db.delete(row);db.commit();return None
    account=db.get(AuthAccount,row.user_id)
    if not account or not account.enabled or account.status!="approved":return None
    last_seen=row.last_seen_at if row.last_seen_at.tzinfo else row.last_seen_at.replace(tzinfo=timezone.utc)
    if (now-last_seen).total_seconds()>300:row.last_seen_at=now;db.commit()
    return account
def safe_account(account:AuthAccount)->dict:return {"id":account.id,"email":decrypt_text(account.email_ciphertext),"name":decrypt_text(account.name_ciphertext),"name_required":not bool(account.name_ciphertext),"role":account.role,"status":account.status,"enabled":account.enabled}

LEGACY_USER_REFERENCE_COLUMNS=(
    ("user_watchlist_items","user_email"),("portfolio_holdings","user_email"),("portfolio_accounts","user_email"),("alert_rules","user_email"),("alert_events","user_email"),("theses","user_email"),("user_access_config","user_email"),("user_preferences","user_email"),("portfolio_definitions","user_email"),("push_subscriptions","user_email"),("alert_delivery_preferences","user_email"),("user_custom_events","user_email"),("refresh_queue","requested_by"),
)

def migrate_legacy_owner_identifiers(db:Session,opaque_user_id:str)->int:
    """Replace the old prototype owner's email-shaped foreign key without exposing it.

    The legacy identifier is selected only by owner role and email-like shape, used as a
    bound SQL parameter, and never returned or logged.
    """
    legacy=db.query(UserProfile).filter(UserProfile.role=="owner",UserProfile.email.like("%@%"),UserProfile.email!=opaque_user_id).first()
    if not legacy:return 0
    old=legacy.email;changed=0
    for table,column in LEGACY_USER_REFERENCE_COLUMNS:
        result=db.execute(text(f'UPDATE "{table}" SET "{column}"=:new_id WHERE "{column}"=:old_id'),{"new_id":opaque_user_id,"old_id":old});changed+=int(result.rowcount or 0)
    legacy.email=opaque_user_id;changed+=1;db.commit();return changed

def ensure_user_defaults(db:Session,account:AuthAccount)->None:
    profile=db.query(UserProfile).filter(UserProfile.email==account.id).first()
    if not profile:db.add(UserProfile(email=account.id,role=account.role,enabled=account.enabled))
    else:profile.role=account.role;profile.enabled=account.enabled
    access=db.get(UserAccessConfig,account.id)
    if not access:db.add(UserAccessConfig(user_email=account.id,enabled=account.enabled,role=account.role,permissions={},allowed_tabs=[]))
    else:access.enabled=account.enabled;access.role=account.role;access.token_hash=None
    if not db.get(UserPreferences,account.id):db.add(UserPreferences(user_email=account.id,visible_tabs=[],information_modules={},settings={}))
    initialized=db.query(UserWatchlistItem).filter(UserWatchlistItem.user_email==account.id,UserWatchlistItem.symbol==SENTINEL).first()
    if not initialized:
        db.add(UserWatchlistItem(user_email=account.id,symbol=SENTINEL))
        for item in db.query(WatchlistItem).order_by(WatchlistItem.created_at).all():
            exists=db.query(UserWatchlistItem).filter(UserWatchlistItem.user_email==account.id,UserWatchlistItem.symbol==item.symbol).first()
            if not exists:db.add(UserWatchlistItem(user_email=account.id,symbol=item.symbol))
    db.commit()

def bootstrap_admin(db:Session)->AuthAccount|None:
    user_id=os.getenv("AUTH_BOOTSTRAP_ADMIN_ID","").strip();email_ciphertext=os.getenv("AUTH_BOOTSTRAP_ADMIN_EMAIL_CIPHERTEXT","").strip();lookup=os.getenv("AUTH_BOOTSTRAP_ADMIN_EMAIL_LOOKUP","").strip();password_hash=os.getenv("AUTH_BOOTSTRAP_ADMIN_PASSWORD_HASH","").strip()
    if not all([user_id,email_ciphertext,lookup,password_hash]):return None
    existing=db.get(AuthAccount,user_id) or db.query(AuthAccount).filter(AuthAccount.email_lookup==lookup).first()
    if existing:migrate_legacy_owner_identifiers(db,existing.id);ensure_user_defaults(db,existing);return existing
    now=datetime.now(timezone.utc);account=AuthAccount(id=user_id,email_ciphertext=email_ciphertext,email_lookup=lookup,password_hash=password_hash,name_ciphertext=None,role="owner",status="approved",enabled=True,approved_at=now);db.add(account);db.commit();migrate_legacy_owner_identifiers(db,account.id);ensure_user_defaults(db,account);return account
