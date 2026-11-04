from __future__ import annotations

import logging

from app.config import Settings


def initialize_monitoring(settings: Settings) -> None:
    dsn = settings.sentry_dsn.get_secret_value().strip()
    if not dsn:
        return
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=dsn,
            environment=settings.environment,
            traces_sample_rate=0.05 if settings.is_production else 0.0,
            send_default_pii=False,
        )
    except Exception:
        logging.getLogger(__name__).exception("Sentry initialization failed; continuing without remote monitoring")
