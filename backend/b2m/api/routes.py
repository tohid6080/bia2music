from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from b2m import __version__
from b2m.api import services as svc
from b2m.api.deps import client_key, current_user, get_db
from b2m.api.schemas import AuthRequest, AuthResponse, DeleteRequest, HomeOut, MeUpdate, UserOut
from b2m.core import tokens
from b2m.core.initdata import InitDataError, validate_init_data
from b2m.db.models import User

log = logging.getLogger("b2m.api")
router = APIRouter(prefix="/api")


def user_out(db: Session, request: Request, u: User) -> dict:
    return dict(id=u.id, first_name=u.first_name, username=u.username, language=u.language,
                is_admin=svc.is_admin(request.app.state.settings, db, u), points=svc.points_total(db, u.id), created_at=u.created_at)


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "version": __version__}


@router.post("/auth/telegram", response_model=AuthResponse)
def auth_telegram(body: AuthRequest, request: Request, db: Session = Depends(get_db)):
    st = request.app.state.settings
    if not request.app.state.limiter.allow(f"auth:{client_key(request)}", st.auth_rate_per_minute):
        raise HTTPException(429, detail="rate_limited")
    try:
        tg = validate_init_data(body.init_data, st.bot_token, st.initdata_max_age_seconds)
    except InitDataError as e:
        svc.log_activity(db, "auth_failed", actor="system", detail={"reason": e.code})       # فقط کُد خطا؛ نه initData
        db.commit()
        log.info("auth rejected: %s", e.code)
        raise HTTPException(401, detail="invalid_init_data") from None
    if tg.is_bot:
        raise HTTPException(401, detail="invalid_init_data")
    user, created = svc.upsert_user(db, st, tg)
    svc.log_activity(db, "signup" if created else "login", user_id=user.id)
    db.commit()
    token, ttl = tokens.issue(user.id, st.jwt_secret, st.jwt_ttl_minutes)
    return {"access_token": token, "expires_in": ttl, "user": user_out(db, request, user)}


@router.get("/me", response_model=UserOut)
def me(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return user_out(db, request, user)


@router.patch("/me", response_model=UserOut)
def update_me(body: MeUpdate, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.language = body.language
    svc.log_activity(db, "language_changed", user_id=user.id, detail={"to": body.language})
    db.commit()
    return user_out(db, request, user)


@router.delete("/me", status_code=204)
def delete_me(body: DeleteRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    svc.delete_account(db, user)
    return Response(status_code=204)


@router.get("/home", response_model=HomeOut)
def home(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.build_home(db, user)
