"""ابزار خط فرمان:  python -m b2m.cli <command>"""
from __future__ import annotations

import argparse
import json
import sys
import time

from b2m.core.config import ConfigError, load_settings


def cmd_init_db(a) -> int:
    from b2m.db import seed
    from b2m.db.migrate import upgrade
    from b2m.db.session import make_engine, make_session_factory

    st = load_settings(require_bot_token=False)
    upgrade(st.database_url)
    with make_session_factory(make_engine(st.database_url))() as db:
        print("دیتابیس آماده شد. داده‌ی مرجع:", seed.seed_reference(db))
    return 0


def cmd_seed_demo(a) -> int:
    from b2m.db import seed
    from b2m.db.session import make_engine, make_session_factory

    st = load_settings(require_bot_token=False)
    if st.is_production:
        print("ممنوع: داده‌ی نمونه در حالت production ساخته نمی‌شود.", file=sys.stderr)
        return 2
    with make_session_factory(make_engine(st.database_url))() as db:
        print("آهنگ نمونه‌ی ساخته‌شده:", seed.seed_demo(db), "(همگی is_demo و آشکارا ساختگی‌اند)")
    return 0


def cmd_check_config(a) -> int:
    st = load_settings()
    print("APP_ENV:", st.app_env)
    print("BOT_TOKEN:", "تنظیم شده" if st.bot_token else "خالی")
    print("ADMIN_USER_ID:", st.admin_user_id or "تنظیم نشده")
    print("WEBAPP_URL:", st.webapp_url or "تنظیم نشده (ربات دکمه‌ی Mini App نمی‌سازد)")
    print("DATABASE:", st.database_url.split("://")[0])
    print("Mini App ساخته‌شده:", "بله" if (st.webapp_dist / "index.html").is_file() else "نه (webapp/dist یافت نشد)")
    return 0


def cmd_dev_initdata(a) -> int:
    """initData امضاشده‌ی معتبر برای تست مرورگر (نیازمند BOT_TOKEN واقعی در .env؛ خروجی را جایی ثبت یا منتشر نکنید)."""
    from b2m.core.initdata import sign

    st = load_settings()
    user = {"id": a.user_id, "first_name": a.first_name, "username": a.username, "language_code": a.lang}
    print(sign({"auth_date": str(int(time.time())), "query_id": "dev", "user": json.dumps(user, separators=(",", ":"), ensure_ascii=False)}, st.bot_token))
    return 0


def cmd_run(a) -> int:
    import uvicorn

    uvicorn.run("b2m.main:app_factory", factory=True, host=a.host, port=a.port, log_level="info")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="b2m")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db").set_defaults(fn=cmd_init_db)
    sub.add_parser("seed-demo").set_defaults(fn=cmd_seed_demo)
    sub.add_parser("check-config").set_defaults(fn=cmd_check_config)
    d = sub.add_parser("dev-initdata")
    d.add_argument("--user-id", type=int, default=100001)
    d.add_argument("--first-name", default="Dev")
    d.add_argument("--username", default="dev_user")
    d.add_argument("--lang", default="fa")
    d.set_defaults(fn=cmd_dev_initdata)
    r = sub.add_parser("run")
    r.add_argument("--host", default="127.0.0.1")
    r.add_argument("--port", type=int, default=8000)
    r.set_defaults(fn=cmd_run)
    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except ConfigError as e:
        print(f"خطای تنظیمات: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
