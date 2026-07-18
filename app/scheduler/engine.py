from __future__ import annotations

import socket
import threading
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.database import Database

VALID_STATES = {
    "queued", "searching", "downloading", "processing",
    "completed", "skipped", "failed",
}


class Scheduler:
    def __init__(
        self, database: Database, timezone_name: str, default_limit: int = 250, processor=None
    ):
        self.database = database
        self.zone = ZoneInfo(timezone_name)
        self.default_limit = default_limit
        self.processor = processor
        self.owner = f"{socket.gethostname()}:{uuid.uuid4().hex}"
        self._thread: threading.Thread | None = None
        self._wake = threading.Event()
        self._shutdown = threading.Event()

    def business_date(self, instant: datetime | None = None) -> str:
        instant = instant or datetime.now(timezone.utc)
        return instant.astimezone(self.zone).date().isoformat()

    def daily_limit(self) -> int:
        return int(self.database.get_setting("daily_limit", str(self.default_limit)))

    def downloads_today(self) -> int:
        with self.database.connect() as db:
            return db.execute(
                "SELECT COUNT(*) FROM download_ledger WHERE business_date=?",
                (self.business_date(),),
            ).fetchone()[0]

    def acquire(self) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as db:
            row = db.execute("SELECT owner,state FROM scheduler_control WHERE singleton=1").fetchone()
            if row["owner"] and row["owner"] != self.owner and row["state"] == "running":
                return False
            db.execute(
                "UPDATE scheduler_control SET owner=?,state='running',heartbeat_at=?,updated_at=? "
                "WHERE singleton=1",
                (self.owner, now, now),
            )
        return True

    def start(self, dry_run: bool) -> bool:
        if self._thread and self._thread.is_alive():
            return False
        if not self.acquire():
            return False
        with self.database.connect() as db:
            db.execute(
                "UPDATE scheduler_control SET dry_run=?,stop_after_current=0 WHERE singleton=1",
                (int(dry_run),),
            )
        self._shutdown.clear()
        self._thread = threading.Thread(target=self._run, name="scheduler", daemon=False)
        self._thread.start()
        return True

    def _run(self) -> None:
        try:
            while not self._shutdown.is_set():
                with self.database.connect() as db:
                    control = db.execute(
                        "SELECT state,stop_after_current FROM scheduler_control WHERE singleton=1"
                    ).fetchone()
                    if control["state"] != "running":
                        self._wake.wait(1)
                        self._wake.clear()
                        continue
                    if self.downloads_today() >= self.daily_limit():
                        db.execute(
                            "UPDATE scheduler_control SET state='paused',updated_at=? WHERE singleton=1",
                            (datetime.now(timezone.utc).isoformat(),),
                        )
                        continue
                    job = db.execute(
                        "SELECT id FROM jobs WHERE state='queued' ORDER BY id LIMIT 1"
                    ).fetchone()
                    if not job:
                        db.execute(
                            "UPDATE scheduler_control SET state='paused',updated_at=? WHERE singleton=1",
                            (datetime.now(timezone.utc).isoformat(),),
                        )
                        continue
                    dry_run = bool(
                        db.execute(
                            "SELECT dry_run FROM scheduler_control WHERE singleton=1"
                        ).fetchone()[0]
                    )
                if self.processor:
                    self.processor(job["id"], dry_run)
                else:
                    with self.database.connect() as db:
                        db.execute(
                            "UPDATE jobs SET state='skipped',message='Dry-run preview complete',"
                            "progress=100,completed_at=?,updated_at=? WHERE id=?",
                            (
                                datetime.now(timezone.utc).isoformat(),
                                datetime.now(timezone.utc).isoformat(),
                                job["id"],
                            ),
                        )
                with self.database.connect() as db:
                    control = db.execute(
                        "SELECT stop_after_current FROM scheduler_control WHERE singleton=1"
                    ).fetchone()
                    if control["stop_after_current"]:
                        db.execute(
                            "UPDATE scheduler_control SET state='paused',stop_after_current=0 WHERE singleton=1"
                        )
        finally:
            with self.database.connect() as db:
                db.execute(
                    "UPDATE scheduler_control SET owner=NULL,state='paused',updated_at=? "
                    "WHERE singleton=1 AND owner=?",
                    (datetime.now(timezone.utc).isoformat(), self.owner),
                )

    def pause(self) -> None:
        with self.database.connect() as db:
            db.execute("UPDATE scheduler_control SET state='paused' WHERE singleton=1")

    def resume(self) -> None:
        with self.database.connect() as db:
            db.execute("UPDATE scheduler_control SET state='running' WHERE singleton=1")
        self._wake.set()

    def stop_after_current(self) -> None:
        with self.database.connect() as db:
            db.execute("UPDATE scheduler_control SET stop_after_current=1 WHERE singleton=1")

    def retry_failed(self) -> int:
        with self.database.connect() as db:
            cursor = db.execute(
                "UPDATE jobs SET state='queued',message='',updated_at=? WHERE state='failed'",
                (datetime.now(timezone.utc).isoformat(),),
            )
            return cursor.rowcount

    def shutdown(self, timeout: float = 20) -> None:
        self._shutdown.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)
