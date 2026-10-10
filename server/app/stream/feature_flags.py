"""
Feature Flag معماری جدید Stream Resolution (Phase 9).

Flag:
  MUSICBAZI_STREAM_V2  (پیش‌فرض: OFF)

وقتی خاموش است، رفتار پروژه دقیقاً همان Production فعلی است؛ هیچ کد جدیدی
مسی‌ر Production را لمس نمی‌کند. وقتی روشن است، Shadow Resolution
(ماژول shadow.py) فعال می‌شود — اما آن هم جایگزین Production نمی‌شود.

پارس strict و قطعی:
  TRUE  = {"1", "true", "yes", "on"}
  FALSE = {"0", "false", "no", "off", ""}   و همچنین unset → OFF
  هر مقدار دیگری (invalid) → OFF + لاگ هشدار

نکته: الگوی موجود app/config.py (_flag) مقدار invalid را ON حساب می‌کند؛
برای یک rollout flag که invariant آن «پیش‌فرض OFF و رفتار امن» است، مقدار
invalid باید OFF باشد. به همین دلیل پارس مستقل و strict اینجاست — framework
جدیدی برای config ساخته نشده و خواندن مستقیم env با الگوی موجود app/stream
(مثل innertubex.py) هم‌خوان است. مقادیر فایل .env هم چون توسط app/config.py
در os.environ تزریق می‌شوند، اینجا به‌صورت یکسان دیده می‌شوند.
"""

from __future__ import annotations

import logging
import os
from typing import Mapping

log = logging.getLogger(__name__)

# نام flag معماری جدید Stream Resolution
STREAM_V2_FLAG = "MUSICBAZI_STREAM_V2"

_FLAG_TRUE = frozenset({"1", "true", "yes", "on"})
_FLAG_FALSE = frozenset({"0", "false", "no", "off", ""})


def parse_bool_flag(raw: str | None) -> bool:
    """
    پارس امن و قطعی مقدار flag. unset/invalid همیشه False (OFF) برمی‌گرداند.
    برای invalid، هشدار لاگ می‌شود اما مقدار خام در پیام نمی‌آید.
    """
    if raw is None:
        return False
    value = raw.strip().lower()
    if value in _FLAG_TRUE:
        return True
    if value in _FLAG_FALSE:
        return False
    log.warning(
        "feature flag %s has an invalid value; treating as OFF",
        STREAM_V2_FLAG,
    )
    return False


def is_stream_v2_enabled(env: Mapping[str, str] | None = None) -> bool:
    """
    وضعیت فعلی flag. پارامتر env فقط برای تست/تزریق است؛ در Production
    os.environ خوانده می‌شود (شامل مقادیر تزریق‌شده از server/.env).
    """
    source = os.environ if env is None else env
    return parse_bool_flag(source.get(STREAM_V2_FLAG))
