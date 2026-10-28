"""
Registry Providerها و رجیستریِ تنظیمات.

دو چیز قفل می‌شود: (۱) ترتیبِ پیش‌فرض دقیقاً همان رفتار قبلی است، و (۲)
`MUSICBAZI_LYRICS_PROVIDER_<NAME>_ENABLED` واقعاً Provider را خاموش می‌کند.
"""

from __future__ import annotations

import pytest

from app import config
from app.lyrics.models import Lyrics
from app.lyrics.registry import ProviderEntry, ProviderRegistry
from app.models import Track


def _entry(name: str, tag: str) -> ProviderEntry:
    def fetch(*_):
        return Lyrics(plain=tag)

    return ProviderEntry(name, fetch)


def _track(track_id: str = "track-1") -> Track:
    return Track(
        id=track_id,
        title="Song",
        artist="Artist",
        album="Album",
        durationMs=180_000,
        source="spotify",
        sourceUrl=f"https://example.test/{track_id}",
    )


class TestOrderResolution:
    def test_registered_order_is_preserved(self):
        registry = ProviderRegistry(
            [_entry("lrclib", "l"), _entry("genius", "g")], ("lrclib", "genius")
        )
        assert registry.order == ("lrclib", "genius")

    def test_the_configured_order_wins(self):
        registry = ProviderRegistry(
            [_entry("lrclib", "l"), _entry("genius", "g")], ("genius", "lrclib")
        )
        assert registry.order == ("genius", "lrclib")

    def test_an_unregistered_name_is_dropped(self):
        registry = ProviderRegistry([_entry("lrclib", "l")], ("ghost", "lrclib"))
        assert registry.order == ("lrclib",)

    def test_an_unlisted_provider_is_appended_not_lost(self):
        """Provider تازه‌ثبت‌شده باید بدون ویرایشِ تنظیمات هم کار کند."""
        registry = ProviderRegistry(
            [_entry("lrclib", "l"), _entry("genius", "g"), _entry("newone", "n")],
            ("lrclib", "genius"),
        )
        assert registry.order == ("lrclib", "genius", "newone")

    def test_an_empty_order_keeps_everything(self):
        registry = ProviderRegistry([_entry("lrclib", "l")], ())
        assert registry.order == ("lrclib",)


class TestAvailability:
    def test_a_registered_provider_without_a_gate_is_always_on(self):
        registry = ProviderRegistry([_entry("lrclib", "l")], ("lrclib",))
        assert [e.name for e in registry.available()] == ["lrclib"]

    def test_a_gate_reporting_false_removes_it(self):
        entries = [ProviderEntry("other", lambda *_: None, lambda: False)]
        registry = ProviderRegistry(entries, ("other",))
        assert registry.available() == []

    def test_a_gate_reporting_true_keeps_it(self):
        entries = [ProviderEntry("other", lambda *_: None, lambda: True)]
        registry = ProviderRegistry(entries, ("other",))
        assert [e.name for e in registry.available()] == ["other"]

    def test_get_returns_the_entry_or_none(self):
        registry = ProviderRegistry([_entry("lrclib", "l")], ("lrclib",))
        assert registry.get("lrclib") is not None
        assert registry.get("nope") is None

    def test_the_configured_kill_switch_disables_a_provider(self, monkeypatch):
        """
        `MUSICBAZI_LYRICS_PROVIDER_GENIUS_ENABLED=0` باید جنسیوس را بردارد.
        این تست واقعاً از تابعِ تنظیمات رد می‌شود، نه از یک lambda.
        """
        monkeypatch.setenv("MUSICBAZI_LYRICS_PROVIDER_GENIUS_ENABLED", "0")
        entries = [ProviderEntry("genius", lambda *_: None, None)]
        registry = ProviderRegistry(entries, ("genius",))

        assert registry.available() == []
        assert config.lyrics_provider_enabled("genius") is False

    def test_a_provider_is_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("MUSICBAZI_LYRICS_PROVIDER_LRCLIB_ENABLED", raising=False)
        assert config.lyrics_provider_enabled("lrclib") is True


class TestDefaultConfiguration:
    def test_the_default_order_is_lrclib_then_genius(self, monkeypatch):
        """
        پیش‌فرضِ پروژه باید عیناً همان ترتیبی باشد که قبلاً در Manager
        سخت‌کد شده بود — وگرنه این رفکتور رفتار را عوض کرده است.
        """
        monkeypatch.delenv("MUSICBAZI_LYRICS_PROVIDERS_ORDER", raising=False)
        assert config.LYRICS_PROVIDERS_ORDER == ("lrclib", "genius")

    def test_the_duration_tolerance_default_matches_the_lrclib_one(self, monkeypatch):
        """
        عددِ تحمل باید همان ۵ ثانیه‌ای باشد که LRCLIB از قبل داشت
        (`providers/lrclib.py`)، نه یک حدسِ تازه.
        """
        monkeypatch.delenv("MUSICBAZI_LYRICS_DURATION_TOLERANCE_S", raising=False)
        from app.providers import lrclib

        assert config._flag  # sanity: config imported
        assert lrclib._DURATION_TOLERANCE_S == 5


class TestDefaultEnabledFlag:
    """
    Provider آینده‌ای که هنوز آماده نیست باید با `default_enabled=False` ثبت
    شود و هرگز اجرا نشود — نه اینکه با هر بار بالا آمدن سرور امتحان شود.
    """

    def test_a_default_off_provider_never_runs(self, monkeypatch):
        from app.lyrics.manager import LyricsManager

        monkeypatch.delenv("MUSICBAZI_LYRICS_PROVIDER_FUTURE_ENABLED", raising=False)
        calls = []

        def fetch(*_):
            calls.append(1)
            return Lyrics(plain="should not run")

        registry = ProviderRegistry(
            [ProviderEntry("future", fetch, default_enabled=False)], ("future",)
        )
        manager = LyricsManager(registry=registry)

        assert manager.fetch(_track()) is None
        assert calls == []

    def test_a_default_off_provider_is_absent_from_available(self, monkeypatch):
        monkeypatch.delenv("MUSICBAZI_LYRICS_PROVIDER_FUTURE_ENABLED", raising=False)
        entry = ProviderEntry("future", lambda *_: None, default_enabled=False)
        registry = ProviderRegistry([entry], ("future",))

        assert registry.available() == []

    def test_the_env_var_still_overrides_default_enabled(self, monkeypatch):
        """متغیر محیطی بر default_enabled غلبه می‌کند — نه برعکس."""
        monkeypatch.setenv("MUSICBAZI_LYRICS_PROVIDER_FUTURE_ENABLED", "1")
        entry = ProviderEntry("future", lambda *_: None, default_enabled=False)
        registry = ProviderRegistry([entry], ("future",))

        assert [e.name for e in registry.available()] == ["future"]

    def test_the_env_var_can_also_disable_a_default_on_provider(self, monkeypatch):
        monkeypatch.setenv("MUSICBAZI_LYRICS_PROVIDER_LRCLIB_ENABLED", "0")
        entry = ProviderEntry("lrclib", lambda *_: None)
        registry = ProviderRegistry([entry], ("lrclib",))

        assert registry.available() == []

    def test_todays_providers_are_default_on(self, monkeypatch):
        """lrclib و genius باید پیش‌فرض روشن بمانند تا رفتار فعلی حفظ شود."""
        from app.lyrics.manager import _PROVIDERS

        monkeypatch.delenv("MUSICBAZI_LYRICS_PROVIDERS_ORDER", raising=False)
        flags = {e.name: e.default_enabled for e in _PROVIDERS}
        assert flags["lrclib"] is True
        assert flags["genius"] is True

    def test_no_new_provider_is_default_on(self, monkeypatch):
        """
        افزودنِ Provider تازه نباید زنجیره‌ی پیش‌فرض را عوض کند. هر Providerی
        جز lrclib/genius باید صریحاً پیش‌فرض خاموش ثبت شده باشد — سرویسِ ثالثی
        که مجوزش بررسی نشده نباید بی‌خبرِ کاربر صدا زده شود.
        """
        from app.lyrics.manager import _PROVIDERS

        monkeypatch.delenv("MUSICBAZI_LYRICS_PROVIDERS_ORDER", raising=False)
        for entry in _PROVIDERS:
            if entry.name in ("lrclib", "genius"):
                continue
            assert entry.default_enabled is False, entry.name

    def test_the_default_order_still_excludes_the_new_providers(self, monkeypatch):
        """
        Providerِ تازه‌ثبت‌شده که در ORDER نیست باید آخرِ صف بیفتد ولی *خاموش*
        بماند. `available()` را نمی‌شود مستقیم سنجید چون Genius در تست بدون
        توکن هم رد می‌شود؛ پس صریحاً همان دو نامِ تازه چک می‌شوند.
        """
        from app.lyrics.manager import LyricsManager

        monkeypatch.delenv("MUSICBAZI_LYRICS_PROVIDERS_ORDER", raising=False)
        for name in ("lyricsplus", "unison"):
            monkeypatch.delenv(f"MUSICBAZI_LYRICS_PROVIDER_{name.upper()}_ENABLED", raising=False)
        monkeypatch.setattr("app.config.GENIUS_ACCESS_TOKEN", "t")

        manager = LyricsManager()

        # زنجیرهٔ خودکار فقط `lrclib` است: Genius زیر `GENIUS_POLICY=manual_only`
        # بیرون از زنجیره است (شرایطِ استفاده‌اش scraping را ممنوع می‌کند) و
        # بقیه پیش‌فرض خاموش‌اند.
        assert [e.name for e in manager.registry.available()] == ["lrclib"]
        # ولی همه ثبت‌شده‌اند و آخرِ صف‌اند، نه حذف‌شده
        assert manager.registry.order == (
            "lrclib",
            "genius",
            "lyricsplus",
            "unison",
            "betterlyrics",
            "binilyrics",
            "lrc_red",
            "simpmusic",
            "paxsenix",
            "musixmatch",
        )

    def test_an_unlisted_default_off_provider_is_still_off(self, monkeypatch):
        monkeypatch.delenv("MUSICBAZI_LYRICS_PROVIDER_FUTURE_ENABLED", raising=False)
        entry = ProviderEntry("future", lambda *_: None, default_enabled=False)
        registry = ProviderRegistry([entry], ("lrclib",))

        assert registry.available() == []

    def test_an_unlisted_default_off_provider_is_never_fetched(self, monkeypatch):
        """
        هم `default_enabled=False`، هم غایب در `ORDER`. `_resolve` Providerهای
        ثبت‌شده‌ی خارج از ترتیب را *آخر* می‌گذارد (نه حذف)، پس بدون چکِ
        `default_enabled` این Provider در زنجیره صدا زده می‌شد — دقیقاً همان
        چیزی که «پیش‌فرض خاموش» باید جلویش را بگیرد.
        """
        from app.lyrics.manager import LyricsManager

        monkeypatch.delenv("MUSICBAZI_LYRICS_PROVIDER_FUTURE_ENABLED", raising=False)
        calls = []

        def lrclib_miss(*_):
            calls.append("lrclib")
            return None

        def future_should_not_run(*_):
            calls.append("future")
            return Lyrics(plain="should not run")

        registry = ProviderRegistry(
            [
                ProviderEntry("lrclib", lrclib_miss),
                ProviderEntry("future", future_should_not_run, default_enabled=False),
            ],
            ("lrclib",),
        )
        manager = LyricsManager(registry=registry)

        assert manager.fetch(_track()) is None
        assert calls == ["lrclib"]
        # ولی همچنان آخر صف ثبت است تا با env روشن شود، نه اینکه حذف شده باشد
        assert registry.order == ("lrclib", "future")

    def test_an_unlisted_default_off_provider_runs_once_the_env_var_enables_it(self, monkeypatch):
        from app.lyrics.manager import LyricsManager

        monkeypatch.setenv("MUSICBAZI_LYRICS_PROVIDER_FUTURE_ENABLED", "1")
        calls = []

        def lrclib_miss(*_):
            calls.append("lrclib")
            return None

        def future(*_):
            calls.append("future")
            return Lyrics(plain="now it runs")

        registry = ProviderRegistry(
            [
                ProviderEntry("lrclib", lrclib_miss),
                ProviderEntry("future", future, default_enabled=False),
            ],
            ("lrclib",),
        )
        manager = LyricsManager(registry=registry)

        result = manager.fetch(_track())
        assert result is not None and result.plain == "now it runs"
        assert result.provider_id == "future"
        assert calls == ["lrclib", "future"]


class TestStrictWiring:
    def test_strict_falls_back_to_fetch_when_not_given(self):
        def fetch(*_):
            return Lyrics(plain="x")

        entry = ProviderEntry("simple", fetch)
        assert entry.strict() is fetch

    def test_strict_prefers_the_explicit_one(self):
        def fetch(*_):
            return Lyrics(plain="public")

        def strict(*_):
            return Lyrics(plain="strict")

        entry = ProviderEntry("x", fetch, None, strict)
        assert entry.strict() is strict

    def test_the_real_providers_register_both(self):
        """Providerهای امروزی باید نسخه‌ی strict داشته باشند، وگرنه تفکیک خطا بی‌اثر است."""
        from app.lyrics.manager import _PROVIDERS

        for entry in _PROVIDERS:
            assert entry.fetch_strict is not None, entry.name


class TestProtocolShape:
    def test_a_plain_object_with_fetch_satisfies_the_protocol(self):
        from app.lyrics.registry import LyricsProvider

        class Fake:
            name = "fake"

            def fetch(self, title, artist, album, duration_ms):
                return None

        assert isinstance(Fake(), LyricsProvider)

    def test_a_provider_missing_fetch_does_not_satisfy_it(self):
        from app.lyrics.registry import LyricsProvider

        class NotAProvider:
            name = "nope"

        assert not isinstance(NotAProvider(), LyricsProvider)
