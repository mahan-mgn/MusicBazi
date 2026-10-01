"""
توزیعِ APK و گزارشِ خطای کلاینت — `/api/release` و `/api/client-error`.

هر دو روی دیسکِ `DATA_DIR` می‌نشینند، پس fixture آن‌ها را به `tmp_path` می‌برد؛
وگرنه تست روی نسخه‌های واقعیِ توسعه‌دهنده دست می‌برد.

بدونِ پلاگین async: همان `asyncio.run` که در `test_setup.py` — `pytest-asyncio`
در حالتِ strict بدونِ مارکر هیچی اجرا نمی‌کند.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import clientlog, releases
from app.main import app


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    """پوشه‌های releases/ و logs/ را به جای موقت می‌بریم."""
    rel = tmp_path / "releases"
    rel.mkdir()
    logs = tmp_path / "logs" / "client.jsonl"
    monkeypatch.setattr(releases, "RELEASES_DIR", rel)
    monkeypatch.setattr(releases, "MANIFEST", rel / "latest.json")
    monkeypatch.setattr(clientlog, "LOG_PATH", logs)
    return rel, logs


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def write_manifest(rel, **data):
    (rel / "latest.json").write_text(json.dumps(data), encoding="utf-8")


class TestRelease:
    def test_no_manifest_is_null(self, dirs, client):
        # سروری که هنوز APK منتشر نکرده باید null بدهد، نه ۵۰۰: اپ این را
        # بی‌صدا می‌بلعد و بنری نشان نمی‌دهد
        assert client.get("/api/release").json() is None

    def test_manifest_without_apk_reports_no_download(self, dirs, client):
        rel, _ = dirs
        write_manifest(rel, versionCode=3, versionName="1.2", notes="x")
        body = client.get("/api/release").json()
        assert body["versionCode"] == 3
        assert body["apkUrl"] is None
        assert body["bytes"] == 0

    def test_apk_present_gives_url_and_size(self, dirs, client):
        rel, _ = dirs
        apk = rel / "musicbazi-1.2.apk"
        apk.write_bytes(b"z" * 1234)
        write_manifest(rel, versionCode=3, versionName="1.2")
        body = client.get("/api/release").json()
        assert body["apkUrl"] == "/api/release/apk"
        assert body["bytes"] == 1234

    def test_apk_download_names_the_file(self, dirs, client):
        rel, _ = dirs
        apk = rel / "musicbazi-1.2.apk"
        apk.write_bytes(b"abc")
        write_manifest(rel, versionCode=3, versionName="1.2")
        res = client.get("/api/release/apk")
        assert res.status_code == 200
        assert "musicbazi-1.2.apk" in res.headers["content-disposition"]
        assert res.headers["content-type"].startswith("application/vnd.android.package-archive")

    def test_apk_404_when_absent(self, dirs, client):
        rel, _ = dirs
        write_manifest(rel, versionCode=3, versionName="1.2")
        assert client.get("/api/release/apk").status_code == 404

    def test_broken_manifest_is_ignored_not_fatal(self, dirs, client):
        # manifestِ نیمه‌نوشته (انتشارِ قطع‌شده) نباید سرور را بخواباند
        rel, _ = dirs
        (rel / "latest.json").write_text("{not json", encoding="utf-8")
        assert client.get("/api/release").json() is None

    def test_non_numeric_version_code_becomes_zero(self, dirs, client):
        # «۱.۲» به‌جای عدد یعنی مقایسه‌ی اپ همیشه «تازه‌تر» بگوید و بنر روی
        # صفحه بچسبد؛ صفر هیچ‌وقت بزرگ‌تر از نسخه‌ی نصب‌شده نیست
        rel, _ = dirs
        write_manifest(rel, versionCode="1.2", versionName="x")
        assert client.get("/api/release").json()["versionCode"] == 0

    def test_file_name_is_flattened(self, dirs, client):
        # `file: "../../etc/passwd"` در manifest نباید راهِ خواندنِ بیرونِ
        # پوشه بدهد — فقط نامِ آخرش حساب می‌شود
        rel, _ = dirs
        write_manifest(rel, versionCode=3, versionName="1.2", file="../../secret.apk")
        assert client.get("/api/release").json()["apkUrl"] is None


class TestClientError:
    def test_record_and_read_back(self, dirs, client):
        res = client.post(
            "/api/client-error",
            json={"kind": "error", "message": "boom", "stack": "at x", "url": "/", "app": "android", "device": "SM-G"},
        )
        assert res.status_code == 200
        assert res.json() == {"ok": True}
        rows = client.get("/api/client-error/recent").json()
        assert rows[0]["message"] == "boom"
        assert rows[0]["kind"] == "error"

    def test_always_200_even_with_empty_body(self, dirs, client):
        # پاسخِ خطا به `window.onerror` خودش خطای دیگری می‌سازد و چرخه ادامه
        # پیدا می‌کند؛ اینجا سکوت لازم است
        res = client.post("/api/client-error", json={"kind": "error"})
        assert res.status_code == 200

    def test_long_fields_are_clipped(self, dirs, client):
        _, logs = dirs
        client.post(
            "/api/client-error",
            json={"kind": "error", "message": "m" * 50000, "stack": "s" * 50000},
        )
        row = json.loads(logs.read_text(encoding="utf-8").splitlines()[-1])
        assert len(row["message"]) <= 4000
        assert len(row["stack"]) <= 4000

    def test_recent_limit_respected(self, dirs, client):
        for i in range(5):
            client.post("/api/client-error", json={"kind": "error", "message": f"e{i}"})
        rows = client.get("/api/client-error/recent", params={"limit": 2}).json()
        assert len(rows) == 2
        assert rows[0]["message"] == "e4"  # تازه‌ترین اول

    def test_trim_keeps_newest(self, dirs, monkeypatch):
        _, logs = dirs
        monkeypatch.setattr(clientlog, "MAX_BYTES", 200)
        for i in range(40):
            assert clientlog.record({"kind": "error", "message": f"line-{i}"})
        kept = clientlog.recent(limit=200)
        assert kept[0]["message"] == "line-39"
        assert logs.stat().st_size < 4000

    def test_empty_log_reads_as_list(self, dirs, client):
        assert client.get("/api/client-error/recent").json() == []
