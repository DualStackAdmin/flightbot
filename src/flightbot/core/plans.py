"""Plan limits (Free / Pro). The numbers come from the initial spec and are changed here."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PlanLimits:
    max_active_watches: int
    max_flexible_watches: int | None  # None = limitsiz
    daily_notifications: int


# The default watch mode is "by month", so a separate flexible limit would break Free's promise of 3 watches.
# The `max_flexible_watches` mechanism is kept (for future plans) but is unlimited for now.
FREE = PlanLimits(max_active_watches=3, max_flexible_watches=None, daily_notifications=3)
PRO = PlanLimits(max_active_watches=25, max_flexible_watches=None, daily_notifications=30)


def effective_plan(plan: str, plan_expires_at: datetime | None, now: datetime) -> str:
    """'free' if Pro has expired. `plan_expires_at=None` with plan='pro' means unlimited (granted by an admin)."""
    if plan == "pro" and (plan_expires_at is None or plan_expires_at > now):
        return "pro"
    return "free"


def limits_for(plan: str) -> PlanLimits:
    return PRO if plan == "pro" else FREE
