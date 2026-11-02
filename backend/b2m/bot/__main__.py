import logging
import sys

from b2m.bot.app import build_application
from b2m.core.config import ConfigError, load_settings


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)       # URL درخواست‌ها شامل توکن است؛ لاگ نشود
    try:
        st = load_settings()
    except ConfigError as e:
        print(f"خطای تنظیمات: {e}", file=sys.stderr)
        return 1
    build_application(st).run_polling(allowed_updates=["message"], drop_pending_updates=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
