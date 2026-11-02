from __future__ import annotations

from typing import Iterator, Optional

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from b2m.core import tokens
from b2m.db.models import User


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as s:
        yield s


def client_key(request: Request) -> str:
    st = request.app.state.settings
    if st.trust_proxy_headers:
        for h in ("cf-connecting-ip", "x-forwarded-for"):
            v = request.headers.get(h)
            if v:
                return v.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"


def current_user(request: Request, authorization: Optional[str] = Header(default=None), db: Session = Depends(get_db)) -> User:
    st = request.app.state.settings
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, detail="unauthorized")
    uid = tokens.verify(authorization[7:].strip(), st.jwt_secret)
    user = db.get(User, uid) if uid else None
    if not user:
        raise HTTPException(401, detail="unauthorized")
    if not request.app.state.limiter.allow(f"u:{user.id}", st.api_rate_per_minute):
        raise HTTPException(429, detail="rate_limited")
    return user
