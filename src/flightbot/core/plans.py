"""Plan limitləri (Free / Pro). Rəqəmlər ilkin spesifikasiyadandır, burada dəyişdirilir."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PlanLimits:
    max_active_watches: int
    max_flexible_watches: int | None  # None = limitsiz
    daily_notifications: int


# Default izləmə rejimi "ay üzrə"dir, ona görə ayrıca çevik limit Free-nin 3 izləmə vədini pozardı.
# `max_flexible_watches` mexanizmi saxlanılır (gələcək planlar üçün), amma indi limitsizdir.
FREE = PlanLimits(max_active_watches=3, max_flexible_watches=None, daily_notifications=3)
PRO = PlanLimits(max_active_watches=25, max_flexible_watches=None, daily_notifications=30)


def effective_plan(plan: str, plan_expires_at: datetime | None, now: datetime) -> str:
    """Pro vaxtı bitibsə 'free'. `plan_expires_at=None` və plan='pro' = müddətsiz (admin tərəfindən)."""
    if plan == "pro" and (plan_expires_at is None or plan_expires_at > now):
        return "pro"
    return "free"


def limits_for(plan: str) -> PlanLimits:
    return PRO if plan == "pro" else FREE
