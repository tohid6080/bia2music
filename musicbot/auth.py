"""کنترل دسترسی: فقط ADMIN_USER_ID (و فقط در چت خصوصی) مدیر است."""
from __future__ import annotations

from typing import Optional

from musicbot.config import Settings
from musicbot.db import Repositories


def is_admin(settings: Settings, repos: Repositories, user_id: Optional[int]) -> bool:
    if user_id is None or user_id != settings.admin_user_id:
        return False
    return repos.admins.is_active_admin(user_id)
