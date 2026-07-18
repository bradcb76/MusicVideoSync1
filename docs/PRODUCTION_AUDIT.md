# Production audit and migration plan

## Safety baseline

- Work is isolated on `feature/full-production-upgrade`.
- The original music source remains mounted at `/music` with Docker `read_only: true`.
- The existing SQLite database was copied before migration to
  `data/backups/music-video-sync-pre-production-20260718-180759.db`.
- Source and backup SHA-256:
  `23D4BEA28D3BF55CA1653D4293F6EF50896B0BFCADB32F49AD249F0AAA24ADCD`.
- Databases, backups, media, staging, processing, logs, caches, and environment files are ignored.
- Development and automated verification use fixture directories. Real media mounts are not processing targets.

## Legacy baseline

The original application was a 3,810-line `app/main.py` containing FastAPI routes,
SQL, background threads, yt-dlp and FFmpeg work, and six large inline HTML screens.
The clean `main` branch exposed 24 routes:

- Scanner dashboard and `/api/scan`, `/api/status`
- Library summary, artist, and track APIs
- YouTube search and artist-hit matching
- Staging and production download endpoints
- Artist batch queue controls
- Scheduler preview, prepare, status, start, stop, and runtime
- `/health`

Legacy tables were created ad hoc: `tracks`, `video_downloads`,
`scheduler_artists`, `scheduler_settings`, and `scheduler_daily`.

## Findings

1. `SCAN_ONLY=true` was unused while `ALLOW_STAGING_DOWNLOADS=true` also enabled
   production output.
2. All state-changing endpoints were unauthenticated and lacked CSRF protection.
3. Port 8787 was published on all interfaces.
4. `scheduler_count_today` and `score_video` were each defined twice.
5. Daily accounting used UTC rather than the Australia/Sydney calendar.
6. Scheduler defaults disagreed (5 vs 10 minimum tracks) and included multiple
   hidden fallbacks to 50.
7. The scheduler only ran after a manual request and did not resume on a new day.
8. Daemon threads, blocking yt-dlp/FFmpeg work, and global dictionaries made
   shutdown and multi-instance operation unsafe.
9. SQLite lacked migration tracking and reliable job state.
10. Cross-filesystem `shutil.move` could expose partial final files.
11. Inline HTML/JavaScript used unsafe `innerHTML` and inline event handlers.
12. `/health` always reported healthy; Docker had no health check.
13. The container ran as root with no init, capability restrictions, or log limits.
14. `yt-dlp`, the Python base image, OS packages, and transitive dependencies were
    not fully locked.
15. Plex and Emby integration did not exist.

## Additive migration strategy

The production upgrade preserves SQLite and the legacy `tracks` table. Migrations
are additive and recorded in `schema_migrations`. New tables provide persistent
settings, jobs, a single download ledger, scheduler ownership/state, sanitised
activity, integration status, and refresh work.

Before startup migration the application creates an additional timestamped SQLite
backup. Production deployment instructions also require an operator backup.

## Controlled implementation phases

1. Add safety tests for path containment, atomic no-overwrite publishing, source
   mount configuration, authentication, CSRF, and Sydney business dates.
2. Modularise configuration, database, services, scheduler, integrations, routers,
   templates, and static assets.
3. Persist job/scheduler state and enforce the saved 250 default before work.
4. Add independent Plex and Emby API clients with redacted failures.
5. Replace inline UI with an accessible responsive application shell.
6. Harden authentication, sessions, rate limits, headers, errors, and paths.
7. Harden Docker and document Windows deployment, backup, and troubleshooting.
8. Run formatting, lint, tests, image build, Compose health/login/dry-run checks,
   and before/after real-media metadata comparison.
