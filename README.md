# MusicVideoSync

Authenticated, dry-run-first FastAPI service for scanning a read-only music library, queueing videos,
and independently refreshing Plex and Emby. See `docs/` for Windows Docker, integration, backup, and
troubleshooting instructions.

Development: `py -m pip install -r requirements-dev.txt`, `ruff check app tests`, `pytest -q`.
