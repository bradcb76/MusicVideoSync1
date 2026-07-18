from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yt_dlp

from app.config import Settings
from app.database import Database
from app.services.media import atomic_publish, ensure_within, safe_component


class DownloadService:
    def __init__(self, database: Database, settings: Settings, business_date, refresh_callback=None):
        self.database, self.settings, self.business_date = database, settings, business_date
        self.refresh_callback = refresh_callback

    def enqueue(self, track_id: int, video_id: str, dry_run: bool) -> int:
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            raise ValueError("Invalid YouTube video ID")
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as db:
            track = db.execute(
                "SELECT id,artist,title FROM tracks WHERE id=?", (track_id,)
            ).fetchone()
            if not track:
                raise ValueError("Track not found")
            artist, title = safe_component(track["artist"]), safe_component(track["title"])
            destination = self.settings.music_video_library / artist / f"{artist} - {title}.mp4"
            ensure_within(destination, self.settings.music_video_library)
            duplicate = db.execute(
                "SELECT id FROM download_ledger WHERE track_id=? OR video_id=? OR destination=?",
                (track_id, video_id, str(destination)),
            ).fetchone()
            if duplicate:
                raise ValueError("Download already completed")
            cursor = db.execute(
                """INSERT INTO jobs(job_type,state,track_id,artist,video_id,destination,dry_run,
                   created_at,updated_at) VALUES('download','queued',?,?,?,?,?,?,?)""",
                (track_id, track["artist"], video_id, str(destination), int(dry_run), now, now),
            )
            return cursor.lastrowid

    def process(self, job_id: int, scheduler_dry_run: bool = False) -> None:
        with self.database.connect() as db:
            job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job or job["state"] != "queued":
                return
            dry_run = bool(job["dry_run"]) or scheduler_dry_run or self.settings.dry_run
            now = datetime.now(timezone.utc).isoformat()
            if dry_run:
                db.execute(
                    "UPDATE jobs SET state='skipped',message='Dry-run: no media changed',"
                    "progress=100,completed_at=?,updated_at=? WHERE id=?",
                    (now, now, job_id),
                )
                return
            if not self.settings.allow_downloads:
                db.execute(
                    "UPDATE jobs SET state='failed',message='Live downloads are disabled',updated_at=? WHERE id=?",
                    (now, job_id),
                )
                return
            db.execute(
                "UPDATE jobs SET state='downloading',attempts=attempts+1,started_at=?,updated_at=? WHERE id=?",
                (now, now, job_id),
            )
        work = ensure_within(self.settings.processing_path / f"job-{job_id}", self.settings.processing_path)
        work.mkdir(parents=True, exist_ok=True)
        diagnostics = ""
        try:
            template = str(work / "source.%(ext)s")
            options = {
                "format": (
                    f"bv*[height<={self.settings.video_quality}]+ba/"
                    f"b[height<={self.settings.video_quality}]"
                ),
                "merge_output_format": "mp4",
                "outtmpl": template,
                "noplaylist": True,
                "retries": 3,
                "fragment_retries": 3,
                "socket_timeout": self.settings.external_timeout,
                "quiet": True,
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(options) as downloader:
                downloader.download([f"https://www.youtube.com/watch?v={job['video_id']}"])
            candidates = [
                item for item in work.iterdir()
                if item.is_file() and item.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
            ]
            if not candidates:
                raise RuntimeError("Downloaded media was not found")
            source = max(candidates, key=lambda item: item.stat().st_size)
            converted = work / "validated.mp4"
            with self.database.connect() as db:
                db.execute(
                    "UPDATE jobs SET state='processing',progress=70,updated_at=? WHERE id=?",
                    (datetime.now(timezone.utc).isoformat(), job_id),
                )
            result = subprocess.run(
                [
                    "ffmpeg", "-nostdin", "-y", "-i", str(source), "-map", "0:v:0",
                    "-map", "0:a:0?", "-c", "copy", "-movflags", "+faststart", str(converted),
                ],
                capture_output=True,
                text=True,
                timeout=max(60, self.settings.external_timeout * 10),
                check=False,
            )
            diagnostics = (result.stderr or "")[-4000:]
            if result.returncode or not converted.exists():
                raise RuntimeError("FFmpeg validation failed")
            destination = ensure_within(Path(job["destination"]), self.settings.music_video_library)
            if destination.exists():
                raise RuntimeError("Destination already exists; refusing to overwrite")
            atomic_publish(converted, destination, self.settings.music_video_library)
            now = datetime.now(timezone.utc).isoformat()
            try:
                with self.database.connect() as db:
                    db.execute(
                        """INSERT INTO download_ledger(job_id,track_id,video_id,destination,
                           business_date,size_bytes,completed_at) VALUES(?,?,?,?,?,?,?)""",
                        (
                            job_id, job["track_id"], job["video_id"], str(destination),
                            self.business_date(), destination.stat().st_size, now,
                        ),
                    )
                    db.execute(
                        "UPDATE jobs SET state='completed',progress=100,message='Completed',"
                        "completed_at=?,updated_at=? WHERE id=?",
                        (now, now, job_id),
                    )
            except Exception:
                destination.unlink(missing_ok=True)
                raise
            if self.refresh_callback:
                # Provider failures are deliberately isolated from the completed media job.
                self.refresh_callback(destination)
            shutil.rmtree(work, ignore_errors=True)
        except Exception as error:
            with self.database.connect() as db:
                db.execute(
                    "UPDATE jobs SET state='failed',message=?,diagnostics=?,updated_at=? WHERE id=?",
                    (
                        str(error)[:500],
                        json.dumps({"ffmpeg_tail": diagnostics})[:5000],
                        datetime.now(timezone.utc).isoformat(),
                        job_id,
                    ),
                )
