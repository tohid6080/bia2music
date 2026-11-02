import random

from musicbot.ai import CaptionRequest, create_provider, get_ai_status
from musicbot.ai import factory
from musicbot.config import load_settings
from tests.conftest import make_env


def S(**o):
    return load_settings(make_env(**o), load_dotenv_file=False)


def test_default_inactive_no_error():
    st = get_ai_status(S())
    assert not st.real_ai_active and "واقعی نیست" in st.content_mode_fa and not st.recognizer_active
    assert create_provider(S()).is_real_ai is False


def test_unknown_provider():
    assert "ناشناخته" in get_ai_status(S(AI_PROVIDER="foo")).reason_fa


def test_key_missing():
    st = get_ai_status(S(AI_PROVIDER="claude"))
    assert not st.real_ai_active and "ANTHROPIC_API_KEY" in st.reason_fa


def test_key_present_but_not_implemented_stays_inactive():
    s = S(AI_PROVIDER="openai", OPENAI_API_KEY="sk-" + "a" * 30)
    st = get_ai_status(s)
    assert not st.real_ai_active and "پیاده‌سازی نشده" in st.reason_fa
    assert create_provider(s).name == "rule_based"
    assert "sk-aaaa" not in st.reason_fa


def test_pluggable_factory(monkeypatch):
    from musicbot.ai.rule_based import RuleBasedProvider

    class Fake(RuleBasedProvider):
        name, is_real_ai = "claude", True

    monkeypatch.setitem(factory.PROVIDER_FACTORIES, "claude", lambda s: Fake())
    s = S(AI_PROVIDER="claude", ANTHROPIC_API_KEY="k" * 20)
    assert get_ai_status(s).real_ai_active and create_provider(s).name == "claude"


async def test_rule_based_caption():
    from musicbot.ai.rule_based import RuleBasedProvider

    p = RuleBasedProvider(random.Random(1))
    r = await p.generate_caption(CaptionRequest(title="شب", artist="علی", language="فارسی", genre="پاپ", mood="عاشقانه"))
    assert "علی" in r.caption and "شب" in r.caption and not r.is_real_ai
    assert "#موزیک_ایرانی" in r.hashtags and "#Bia2Music" in r.hashtags and len(set(r.hashtags)) == len(r.hashtags)
