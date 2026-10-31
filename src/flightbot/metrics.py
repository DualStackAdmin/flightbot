"""Prometheus metrics. The 3 key indicators from the original plan plus extras:

- provider_cache (hit/miss)      -> cache hit ratio, target > 85%
- telegram_errors{type}          -> 429 error rate, target = 0
- notification_queue_lag_seconds -> notification queue lag
"""

from prometheus_client import Counter, Gauge, Histogram, start_http_server

PROVIDER_REQUESTS = Counter("provider_requests_total", "Requests to the provider", ["provider", "status"])
PROVIDER_CACHE = Counter("provider_cache_total", "Provider cache", ["result"])
POLL_DURATION = Histogram("poll_duration_seconds", "Time to check one watch_key")
POLLED_KEYS = Counter("polled_keys_total", "Checked watch_keys", ["outcome"])
ALERT_DECISIONS = Counter("alert_decisions_total", "Alert engine decisions", ["verdict"])
NOTIFICATIONS = Counter("notifications_total", "Notification outcomes", ["status"])
TELEGRAM_ERRORS = Counter("telegram_errors_total", "Telegram errors", ["type"])
QUEUE_LAG = Gauge("notification_queue_lag_seconds", "Age of the oldest pending notification")
QUEUE_DEPTH = Gauge("notification_queue_depth", "Number of pending notifications")
DUE_KEYS = Gauge("due_watch_keys", "Number of due watch_keys")
COUNT_DRIFT = Counter("active_watch_count_drift_total", "Counter drift (fixed by reconcile)")


def start_metrics_server(port: int) -> None:
    start_http_server(port)
