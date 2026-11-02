"""تنظیم لاگ‌گیری با پنهان‌سازی خودکار توکن ربات."""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_TOKEN_PATTERN = re.compile(r"(?<!\d)\d{6,}:[A-Za-z0-9_-]{30,}")
_KEY_PATTERN = re.compile(r"\b(sk-[A-Za-z0-9_-]{16,})")
_QUERY_KEY = re.compile(r"((?:api_key|key)=)[^&\s\"']+", re.I)
_GOOGLE_KEY = re.compile(r"\bAIza[0-9A-Za-z_-]{20,}")


def redact(text: str) -> str:
    text = _TOKEN_PATTERN.sub("<TOKEN>", text)
    text = _KEY_PATTERN.sub("<KEY>", text)
    text = _GOOGLE_KEY.sub("<KEY>", text)
    return _QUERY_KEY.sub(r"\1<KEY>", text)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        record.msg = redact(message)
        record.args = None
        if record.exc_info:
            # traceback متن را در format می‌سازد؛ فرمتر امن آن را پاکسازی می‌کند.
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


def setup_logging(level: str = "INFO", log_dir: Path = Path("logs")) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    flt = RedactingFilter()

    console = logging.StreamHandler()
    file_handler = RotatingFileHandler(log_dir / "bot.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    for h in (console, file_handler):
        h.setFormatter(fmt)
        h.addFilter(flt)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(console)
    root.addHandler(file_handler)
    # این لاگرها URL کامل (حاوی توکن) را چاپ می‌کنند.
    for noisy in ("httpx", "httpcore", "telegram.ext.ExtBot"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
