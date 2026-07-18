from __future__ import annotations

import threading
from pathlib import Path

from mutagen import File as MutagenFile

from app.database import Database

AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma", ".alac"}


class LibraryScanner:
    def __init__(self, database: Database, root: Path):
        self.database, self.root = database, root
        self._lock = threading.Lock()
        self.status = {
            "running": False, "scanned": 0, "identified": 0,
            "unidentified": 0, "current_file": "", "error": "",
        }

    @staticmethod
    def _tag(tags, *names: str) -> str:
        for name in names:
            value = tags.get(name) if tags else None
            if value:
                return str(value[0] if isinstance(value, list) else value).strip()
        return ""

    def scan(self) -> None:
        if not self._lock.acquire(blocking=False):
            return
        self.status.update(running=True, scanned=0, identified=0, unidentified=0, error="")
        try:
            with self.database.connect() as db:
                for path in self.root.rglob("*"):
                    if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
                        continue
                    self.status["scanned"] += 1
                    self.status["current_file"] = str(path)
                    artist = album = title = track_number = ""
                    duration = 0.0
                    try:
                        audio = MutagenFile(path, easy=True)
                        if audio:
                            artist = self._tag(audio.tags, "artist", "albumartist")
                            album = self._tag(audio.tags, "album")
                            title = self._tag(audio.tags, "title")
                            track_number = self._tag(audio.tags, "tracknumber")
                            duration = round(getattr(audio.info, "length", 0) or 0, 2)
                    except Exception:
                        pass
                    key = "identified" if artist and title else "unidentified"
                    self.status[key] += 1
                    db.execute(
                        """INSERT INTO tracks(file_path,filename,artist,album,title,track_number,
                           duration_seconds,extension) VALUES(?,?,?,?,?,?,?,?)
                           ON CONFLICT(file_path) DO UPDATE SET filename=excluded.filename,
                           artist=excluded.artist,album=excluded.album,title=excluded.title,
                           track_number=excluded.track_number,duration_seconds=excluded.duration_seconds,
                           extension=excluded.extension""",
                        (str(path), path.name, artist, album, title, track_number, duration, path.suffix.lower()),
                    )
        except Exception as error:
            self.status["error"] = f"{type(error).__name__}: scan failed"
        finally:
            self.status.update(running=False, current_file="")
            self._lock.release()
