"""برنامه‌ی FastAPI: API + (اختیاری) سرو فایل‌های ساخته‌شده‌ی Mini App از همان دامنه‌ی HTTPS."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from b2m import __version__
from b2m.api.routes import router
from b2m.core.config import Settings, load_settings
from b2m.core.ratelimit import RateLimiter
from b2m.db.session import make_engine, make_session_factory

CSP = ("default-src 'self'; script-src 'self' https://telegram.org; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; "
       "connect-src 'self'; base-uri 'none'; object-src 'none'")


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        if not request.url.path.startswith("/api"):
            resp.headers.setdefault("Content-Security-Policy", CSP)
        else:
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp


def create_app(settings: Optional[Settings] = None, engine=None) -> FastAPI:
    st = settings or load_settings()
    app = FastAPI(title="Bia2Music API", version=__version__, docs_url="/api/docs" if not st.is_production else None,
                  redoc_url=None, openapi_url="/api/openapi.json" if not st.is_production else None)
    app.state.settings = st
    app.state.engine = engine or make_engine(st.database_url)
    app.state.session_factory = make_session_factory(app.state.engine)
    app.state.limiter = RateLimiter()
    app.add_middleware(SecurityHeaders)
    if st.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(st.cors_origins), allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])

    @app.exception_handler(HTTPException)
    async def http_err(_: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail if isinstance(exc.detail, str) else "error"}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def val_err(_: Request, __: RequestValidationError):          # ورودی کاربر در پاسخ/لاگ بازتاب داده نمی‌شود
        return JSONResponse({"error": "invalid_request"}, status_code=422)

    app.include_router(router)
    dist = st.webapp_dist
    if st.serve_webapp and (dist / "index.html").is_file():
        if (dist / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api"):
                raise HTTPException(404, detail="not_found")
            f = (dist / path).resolve()
            if path and f.is_file() and dist.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})
    return app


def app_factory() -> FastAPI:          # uvicorn b2m.main:app_factory --factory
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()
