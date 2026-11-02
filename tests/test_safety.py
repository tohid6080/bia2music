"""بررسی‌های ایمنی: بدون راز در کد، بدون هیچ کد انتشار در مرحله ۱، پنهان‌سازی توکن در لاگ."""
import ast
import logging
import re
from pathlib import Path

from musicbot.logging_setup import RedactingFilter, redact
from tests.conftest import TOKEN

SRC = Path(__file__).parent.parent / "musicbot"
FORBIDDEN_PUBLISH = re.compile(r"\b(send_audio|send_message_to_channel|send_voice|copy_message|send_media_group)\b")


def _py(path):
    return [f for f in SRC.rglob("*.py") if f.name != "__pycache__"]


def test_telegram_send_calls_confined_to_publishing_service():
    """ارسال فایل/پیام رسانه‌ای فقط در publishing/service.py مجاز است (پیش‌نمایش و انتشار)."""
    allowed = SRC / "publishing" / "service.py"
    for f in _py(SRC):
        if f != allowed:
            assert not FORBIDDEN_PUBLISH.search(f.read_text()), f
    assert len(re.findall(r"\.send_audio\(", allowed.read_text())) == 3  # send_preview + publish_now + send_song_to_user


def _send_calls(path, attr):
    tree = ast.parse(path.read_text())
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == attr]


def _target(call):
    """عبارت مقصد (chat_id) یک فراخوانی ارسال، چه موضعی چه کلیدواژه‌ای."""
    for k in call.keywords:
        if k.arg == "chat_id":
            return ast.unparse(k.value)
    return ast.unparse(call.args[0]) if call.args else ""


def test_send_targets_are_pinned():
    svc = SRC / "publishing" / "service.py"
    targets = sorted(_target(c) for c in _send_calls(svc, "send_audio"))
    assert targets == ["channel_ref", "chat_id", "user_id"]       # کانال فقط در publish_now؛ مدیر در پیش‌نمایش؛ کاربر در send_song_to_user
    msgs = [_target(c) for c in _send_calls(svc, "send_message")]
    assert sorted(msgs) == ["channel_ref", "chat_id"]              # پست تبلیغی (کانال) + پیش‌نمایش آن (مدیر)
    # هیچ جای دیگر پیامی به «کانال» نمی‌رود
    for f in _py(SRC):
        if f == svc:
            continue
        for call in _send_calls(f, "send_message"):
            assert "channel" not in _target(call).lower(), (f, ast.unparse(call))
        for attr in ("send_audio", "send_document", "send_photo", "send_voice", "send_video"):
            if (attr == "send_document" and f.name == "settings.py") or (attr == "send_photo" and f.name == "growth.py"):
                assert all("admin_user_id" in _target(c) for c in _send_calls(f, attr))   # پشتیبان و QR فقط به چت مدیر
            else:
                assert not _send_calls(f, attr), (f, attr)


def test_forward_confined_to_importer_and_targets_admin_only():
    """فوروارد (برای درون‌ریزی) فقط در importer.py، فقط یک‌جا، و مقصدش همیشه چت خود مدیر است."""
    hits = [f for f in _py(SRC) if "forward_message" in f.read_text()]
    assert [f.name for f in hits] == ["importer.py"]
    tree = ast.parse(hits[0].read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "forward_message"]
    assert len(calls) == 1
    kw = {k.arg: ast.unparse(k.value) for k in calls[0].keywords}
    assert kw["chat_id"] == "self.admin_id" and kw["from_chat_id"] == "self.channel_ref"


def _calls_of(func_name):
    """(فایل، تابع حاوی فراخوانی) برای همه فراخوانی‌های func_name به‌جز تعریف خود تابع."""
    found = []
    for f in _py(SRC):
        tree = ast.parse(f.read_text())
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for node in ast.walk(fn):
                    if isinstance(node, ast.Call):
                        name = getattr(node.func, "id", getattr(node.func, "attr", None))
                        if name == func_name and fn.name != func_name:
                            found.append((f.relative_to(SRC).as_posix(), fn.name))
    return found


def test_publish_now_has_exactly_one_caller():
    assert set(_calls_of("publish_now")) == {("handlers/publish.py", "_go")}


def test_ad_and_download_have_single_callers():
    assert set(_calls_of("publish_ad_now")) == {("handlers/campaigns.py", "_go")}
    assert set(_calls_of("send_song_to_user")) == {("handlers/users.py", "_download")}


def test_scheduler_cannot_publish():
    text = (SRC / "publishing" / "scheduler.py").read_text()
    for banned in ("publish_now", "publish_ad_now", "publishing.service", "send_audio", "send_song_to_user",
                   "claim_for_publishing", "mark_published", "claim_publishing"):
        assert banned not in text
    assert not _calls_of("claim_for_publishing") or all(c[0] == "publishing/service.py" for c in _calls_of("claim_for_publishing"))


def test_go_only_reachable_from_confirm_button():
    src = (SRC / "handlers" / "publish.py").read_text()
    assert src.count("_go(update, context, sid, parts[3])") == 1
    assert src.count('action == "go"') == 1


def test_no_secrets_in_source():
    for f in list(SRC.rglob("*.py")):
        t = f.read_text()
        assert not re.search(r"\b\d{6,}:[A-Za-z0-9_-]{30,}", t), f
        assert not re.search(r"sk-[A-Za-z0-9]{20,}", t), f


def test_env_example_has_no_values_for_secrets():
    env = (SRC.parent / ".env.example").read_text()
    for key in ("TELEGRAM_BOT_TOKEN", "ADMIN_USER_ID", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        assert re.search(rf"^{key}=$", env, re.M)
    assert ".env" in (SRC.parent / ".gitignore").read_text().splitlines()


def test_redact_token():
    assert TOKEN not in redact(f"GET https://api.telegram.org/bot{TOKEN}/getMe")


def test_filter_cleans_log_record():
    rec = logging.LogRecord("x", logging.ERROR, "", 0, "url %s", (f"bot{TOKEN}",), None)
    RedactingFilter().filter(rec)
    assert TOKEN not in rec.getMessage()


FORBIDDEN_ACTIONS = ("approve_chat_join_request", "decline_chat_join_request", "ban_chat_member", "unban_chat_member",
                     "restrict_chat_member", "promote_chat_member", "export_chat_invite_link", "set_chat_administrator_custom_title",
                     "add_chat_member", "create_chat_subscription_invite_link")


def test_no_forced_membership_or_mass_actions():
    """رشد فقط با لینک دعوت داوطلبانه: ربات هیچ‌کدام از این متدها (عضویت اجباری، افزودن افراد، مدیریت اعضا) را ندارد."""
    for f in _py(SRC):
        t = f.read_text()
        for name in FORBIDDEN_ACTIONS:
            assert name not in t, (f.name, name)


def test_growth_module_never_messages_members():
    src = (SRC / "handlers" / "growth.py").read_text()
    for name in ("send_message", "copy_message", "forward_message", "send_audio", "reply_to_users"):
        assert f".{name}(" not in src
    assert "user_data" in src and "for u in users" not in src


def test_chat_member_updates_requested():
    app_src = (SRC / "app.py").read_text()
    assert "Update.CHAT_MEMBER" in app_src and "ChatMemberHandler" in app_src


def test_channel_post_edits_confined_to_promo_backfill():
    """ویرایش پست‌های کانال فقط در promo_backfill.py (فقط reply_markup)؛ هیچ‌جا ویرایش کپشن/متن پست کانال نیست."""
    for f in _py(SRC):
        t = f.read_text()
        if f.name != "promo_backfill.py":
            assert "bot.edit_message_reply_markup" not in t, f
        assert "edit_message_caption" not in t and "edit_message_media" not in t, f
    calls = _send_calls(SRC / "promo_backfill.py", "edit_message_reply_markup")
    assert len(calls) == 1 and _target(calls[0]) == "self.channel_ref"
    assert "edit_message_text" not in (SRC / "promo_backfill.py").read_text()
