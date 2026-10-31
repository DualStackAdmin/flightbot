"""Sakit saatlar: gecə bildirişi yatmış istifadəçini oyatmasın (bloklamanın əsas səbəblərindən biridir)."""

import random
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

JITTER_MAX_S = 15 * 60  # səhər 08:00-da hamıya eyni anda yağmasın


def in_quiet_window(local_hour: int, start_hour: int, end_hour: int) -> bool:
    if start_hour == end_hour:
        return False  # söndürülüb
    if start_hour > end_hour:  # gecə yarısını keçir, məs. 23 -> 8
        return local_hour >= start_hour or local_hour < end_hour
    return start_hour <= local_hour < end_hour


def deliver_after(
    now: datetime,
    *,
    tz: str,
    start_hour: int,
    end_hour: int,
    rng: random.Random | None = None,
) -> datetime:
    """Sakit pəncərədədirsə pəncərənin sonu (+0-15 dəq jitter), əks halda `now`."""
    local = now.astimezone(ZoneInfo(tz))
    if not in_quiet_window(local.hour, start_hour, end_hour):
        return now
    end_local = local.replace(hour=end_hour, minute=0, second=0, microsecond=0)
    if end_local <= local:
        end_local += timedelta(days=1)
    jitter = (rng or random).uniform(0, JITTER_MAX_S)
    return (end_local + timedelta(seconds=jitter)).astimezone(UTC)
