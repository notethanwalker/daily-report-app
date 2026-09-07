from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth_models import AuthAccount, AuthSession
from ..database import get_db
from ..services.auth_security import SESSION_COOKIE, SESSION_DAYS, account_from_session, create_session, decrypt_text, email_lookup, encrypt_text, ensure_user_defaults, hash_password, normalize_email, revoke_all_sessions, revoke_session, safe_account, validate_password, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
_login_attempts: dict[str, deque[float]] = defaultdict(deque)
_register_attempts: dict[str, deque[float]] = defaultdict(deque)

class Credentials(BaseModel):
    email: str
    password: str
class ProfileUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    current_password: str | None = None
class PasswordUpdate(BaseModel):
    current_password: str
    new_password: str


def _client_key(request: Request, suffix: str) -> str:
    ip = request.client.host if request.client else "unknown"
    return f"{ip}:{suffix}"

def _rate_limit(store: dict[str, deque[float]], key: str, max_attempts: int, window_seconds: int) -> None:
    now=time.time();q=store[key]
    while q and q[0]<now-window_seconds:q.popleft()
    if len(q)>=max_attempts:raise HTTPException(429,"Too many attempts. Try again later.")
    q.append(now)
def _clear_rate(store: dict[str, deque[float]], key: str) -> None:store.pop(key,None)
def _set_session_cookie(response: Response, token: str) -> None:response.set_cookie(SESSION_COOKIE,token,max_age=SESSION_DAYS*24*60*60,httponly=True,secure=True,samesite="lax",path="/")
def _account_or_401(request: Request, db: Session) -> AuthAccount:
    account=account_from_session(db,request.cookies.get(SESSION_COOKIE))
    if not account:raise HTTPException(401,"Authentication required")
    return account
def _owner_or_403(request: Request, db: Session) -> AuthAccount:
    account=_account_or_401(request,db)
    if account.role!="owner":raise HTTPException(403,"Administrator permission required")
    return account

@router.post("/register")
def register(body: Credentials, request: Request, db: Session = Depends(get_db)):
    _rate_limit(_register_attempts,_client_key(request,"register"),5,3600)
    try:email=normalize_email(body.email);validate_password(body.password)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    lookup=email_lookup(email);existing=db.query(AuthAccount).filter(AuthAccount.email_lookup==lookup).first()
    if not existing:
        account=AuthAccount(id="usr_"+secrets.token_hex(16),email_ciphertext=encrypt_text(email),email_lookup=lookup,password_hash=hash_password(body.password),name_ciphertext=None,role="approved_user",status="pending",enabled=False)
        db.add(account);db.commit()
    return {"status":"pending","message":"Account request submitted. The administrator can approve or deny it from Settings."}

@router.post("/login")
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    try:lookup=email_lookup(normalize_email(body.email))
    except ValueError:lookup="invalid"
    rate_key=_client_key(request,lookup[:16]);_rate_limit(_login_attempts,rate_key,10,900)
    account=db.query(AuthAccount).filter(AuthAccount.email_lookup==lookup).first() if lookup!="invalid" else None
    if not account or not verify_password(body.password,account.password_hash):raise HTTPException(401,"Invalid email or password")
    if account.status=="pending":raise HTTPException(403,"Account is awaiting administrator approval")
    if account.status=="rejected" or not account.enabled:raise HTTPException(403,"Account access is not enabled")
    _clear_rate(_login_attempts,rate_key);token=create_session(db,account.id);account.last_login_at=datetime.now(timezone.utc);db.commit();_set_session_cookie(response,token)
    return {"account":safe_account(account)}

@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    revoke_session(db,request.cookies.get(SESSION_COOKIE));response.delete_cookie(SESSION_COOKIE,path="/",secure=True,httponly=True,samesite="lax");return {"status":"signed_out"}
@router.get("/session")
def session(request: Request, db: Session = Depends(get_db)):return {"account":safe_account(_account_or_401(request,db))}

@router.put("/profile")
def update_profile(body: ProfileUpdate, request: Request, db: Session = Depends(get_db)):
    account=_account_or_401(request,db)
    if body.name is not None:
        name=body.name.strip()
        if not name or len(name)>100:raise HTTPException(400,"Name must be between 1 and 100 characters")
        account.name_ciphertext=encrypt_text(name)
    if body.email is not None:
        try:new_email=normalize_email(body.email)
        except ValueError as exc:raise HTTPException(400,str(exc)) from exc
        current_email=decrypt_text(account.email_ciphertext) or ""
        if new_email!=current_email:
            if not body.current_password or not verify_password(body.current_password,account.password_hash):raise HTTPException(401,"Current password is required to change email")
            new_lookup=email_lookup(new_email);duplicate=db.query(AuthAccount).filter(AuthAccount.email_lookup==new_lookup,AuthAccount.id!=account.id).first()
            if duplicate:raise HTTPException(409,"That email address is already registered")
            account.email_ciphertext=encrypt_text(new_email);account.email_lookup=new_lookup
    db.commit();return {"account":safe_account(account)}

@router.put("/password")
def update_password(body: PasswordUpdate, request: Request, response: Response, db: Session = Depends(get_db)):
    account=_account_or_401(request,db)
    if not verify_password(body.current_password,account.password_hash):raise HTTPException(401,"Current password is incorrect")
    try:validate_password(body.new_password)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    account.password_hash=hash_password(body.new_password);db.commit();revoke_all_sessions(db,account.id);token=create_session(db,account.id);_set_session_cookie(response,token);return {"status":"password_updated"}

@router.get("/admin/pending")
def pending_accounts(request: Request, db: Session = Depends(get_db)):
    _owner_or_403(request,db);rows=db.query(AuthAccount).filter(AuthAccount.status=="pending").order_by(AuthAccount.created_at.asc()).all()
    return {"accounts":[{"id":row.id,"email":decrypt_text(row.email_ciphertext),"created_at":row.created_at.isoformat() if row.created_at else None} for row in rows]}
@router.post("/admin/accounts/{user_id}/approve")
def approve_account(user_id: str, request: Request, db: Session = Depends(get_db)):
    _owner_or_403(request,db);account=db.get(AuthAccount,user_id)
    if not account:raise HTTPException(404,"Account request not found")
    account.status="approved";account.enabled=True;account.approved_at=datetime.now(timezone.utc);db.commit();ensure_user_defaults(db,account)
    return {"status":"approved","id":account.id}
@router.post("/admin/accounts/{user_id}/reject")
def reject_account(user_id: str, request: Request, db: Session = Depends(get_db)):
    _owner_or_403(request,db);account=db.get(AuthAccount,user_id)
    if not account:raise HTTPException(404,"Account request not found")
    account.status="rejected";account.enabled=False;db.commit();db.query(AuthSession).filter(AuthSession.user_id==account.id).delete(synchronize_session=False);db.commit()
    return {"status":"rejected","id":account.id}
