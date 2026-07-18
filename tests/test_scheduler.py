from datetime import datetime, timezone

from app.database import Database
from app.scheduler.engine import Scheduler


def test_default_limit_is_250(test_settings):
    database = Database(test_settings.database_path)
    database.migrate()
    scheduler = Scheduler(database, "Australia/Sydney")
    assert scheduler.daily_limit() == 250


def test_sydney_business_date_crosses_utc_boundary(test_settings):
    database = Database(test_settings.database_path)
    database.migrate()
    scheduler = Scheduler(database, "Australia/Sydney")
    instant = datetime(2026, 7, 17, 15, 30, tzinfo=timezone.utc)
    assert scheduler.business_date(instant) == "2026-07-18"


def test_sydney_dst_business_date(test_settings):
    database = Database(test_settings.database_path)
    database.migrate()
    scheduler = Scheduler(database, "Australia/Sydney")
    instant = datetime(2026, 1, 1, 13, 30, tzinfo=timezone.utc)
    assert scheduler.business_date(instant) == "2026-01-02"
