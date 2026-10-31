"""Prometheus metrikaları. Sənəddə tələb olunan 3 əsas göstərici + əlavələr:

- provider_cache (hit/miss)     -> Cache Hit Ratio, hədəf > 85%
- telegram_errors{type}         -> 429 Error Rate, hədəf = 0
- notification_queue_lag_seconds -> Notification Queue Lag
"""

from prometheus_client import Counter, Gauge, Histogram, start_http_server

PROVIDER_REQUESTS = Counter("provider_requests_total", "Provayderə sorğular", ["provider", "status"])
PROVIDER_CACHE = Counter("provider_cache_total", "Provayder keşi", ["result"])
POLL_DURATION = Histogram("poll_duration_seconds", "Bir watch_key yoxlanma müddəti")
POLLED_KEYS = Counter("polled_keys_total", "Yoxlanmış watch_key-lər", ["outcome"])
ALERT_DECISIONS = Counter("alert_decisions_total", "Alert mühərriki qərarları", ["verdict"])
NOTIFICATIONS = Counter("notifications_total", "Bildirişlərin nəticəsi", ["status"])
TELEGRAM_ERRORS = Counter("telegram_errors_total", "Telegram xətaları", ["type"])
QUEUE_LAG = Gauge("notification_queue_lag_seconds", "Ən köhnə gözləyən bildirişin yaşı")
QUEUE_DEPTH = Gauge("notification_queue_depth", "Gözləyən bildirişlərin sayı")
DUE_KEYS = Gauge("due_watch_keys", "Vaxtı çatmış watch_key sayı")
COUNT_DRIFT = Counter("active_watch_count_drift_total", "Sayğac sürüşməsi (reconcile tərəfindən düzəldildi)")


def start_metrics_server(port: int) -> None:
    start_http_server(port)
