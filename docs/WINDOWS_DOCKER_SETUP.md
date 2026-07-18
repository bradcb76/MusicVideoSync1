# Windows Docker Desktop setup

Share `D:\Music`, `D:\Music Videos`, and `C:\MusicVideoSync` in Docker Desktop. Copy `.env.example`
to `.env`, set a strong session secret and administrator password hash, then run `docker compose build`
and `docker compose up -d`. Keep dry-run enabled until the queue is reviewed. The `/music` mount is
permanently read-only.
