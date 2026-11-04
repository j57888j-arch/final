from datetime import datetime, timezone

from app.core.dates import as_utc


def test_naive_database_datetime_is_treated_as_utc():
    value = datetime(2026, 11, 4, 12, 30)
    normalized = as_utc(value)
    assert normalized == datetime(2026, 11, 4, 12, 30, tzinfo=timezone.utc)


def test_aware_datetime_is_converted_to_utc():
    from datetime import timedelta

    value = datetime(2026, 11, 4, 17, 30, tzinfo=timezone(timedelta(hours=5)))
    assert as_utc(value) == datetime(2026, 11, 4, 12, 30, tzinfo=timezone.utc)
