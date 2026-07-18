from __future__ import annotations

import logging
import shutil
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import yt_dlp
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.config import Settings, settings
from app.database import Database
from app.integrations.coordinator import IntegrationCoordinator
from app.logging_config import configure_logging
from app.scheduler.engine import Scheduler
from app.schemas import LoginRequest, QueueRequest, SchedulerStartRequest, SettingsRequest
from app.security import RateLimiter, new_csrf, require_auth, require_csrf, verify_password
from app.services.downloads import DownloadService
from app.services.library import LibraryScanner
from app.services.media import validate_ffmpeg

configure_logging(settings.log_level)
logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")
login_limiter = RateLimiter(5, 300)
action_limiter = RateLimiter(20, 60)


def create_app(config: Settings = settings) -> FastAPI:
    database = Database(config.database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        errors = config.validate()
        if errors:
            raise RuntimeError("; ".join(errors))
        for path in (config.database_path.parent, config.staging_path, config.processing_path):
            path.mkdir(parents=True, exist_ok=True)
        backup = database.backup(config.database_path.parent / "backups")
        if backup:
            logger.info("Pre-migration database backup created")
        database.migrate()
        database.set_setting(
            "daily_limit", database.get_setting("daily_limit", str(config.daily_limit))
        )
        ffmpeg_ok, ffmpeg_version = validate_ffmpeg()
        app.state.ffmpeg = {"ok": ffmpeg_ok, "version": ffmpeg_version}
        app.state.database = database
        app.state.scanner = LibraryScanner(database, config.music_library)
        app.state.integrations = IntegrationCoordinator(database, config)
        scheduler = Scheduler(database, config.timezone, config.daily_limit)
        downloads = DownloadService(database, config, scheduler.business_date)
        downloads.refresh_callback = app.state.integrations.refresh_all
        scheduler.processor = downloads.process
        app.state.scheduler = scheduler
        app.state.downloads = downloads
        yield
        scheduler.shutdown()

    docs_url = "/docs" if config.docs_enabled else None
    application = FastAPI(
        title="MusicVideoSync", version="2.0.0", docs_url=docs_url,
        redoc_url=None, openapi_url="/openapi.json" if config.docs_enabled else None,
        lifespan=lifespan,
    )
    application.add_middleware(
        SessionMiddleware,
        secret_key=config.session_secret,
        session_cookie="mvs_session",
        same_site="strict",
        https_only=False,
        max_age=8 * 60 * 60,
    )
    application.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                "Content-Security-Policy": (
                    "default-src 'self'; style-src 'self'; script-src 'self'; "
                    "img-src 'self' data: https:; connect-src 'self'"
                ),
            }
        )
        return response

    @application.exception_handler(HTTPException)
    async def http_error(_request: Request, error: HTTPException):
        return JSONResponse(
            {"error": {"code": error.status_code, "message": str(error.detail)}},
            status_code=error.status_code,
        )

    @application.exception_handler(Exception)
    async def unexpected_error(_request: Request, error: Exception):
        logger.exception("Unhandled request failure")
        return JSONResponse(
            {"error": {"code": 500, "message": "An internal error occurred"}},
            status_code=500,
        )

    def page(request: Request, name: str, **context):
        if not request.session.get("authenticated"):
            return RedirectResponse("/login", 303)
        return templates.TemplateResponse(
            request, name, {"csrf": request.session["csrf"], "dry_run": config.dry_run, **context}
        )

    @application.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        return templates.TemplateResponse(request, "login.html", {})

    @application.post("/api/auth/login")
    def login(payload: LoginRequest, request: Request):
        client = request.client.host if request.client else "unknown"
        login_limiter.check(client)
        if not config.admin_password_hash or not verify_password(payload.password, config.admin_password_hash):
            raise HTTPException(401, "Invalid credentials")
        request.session.clear()
        request.session.update(authenticated=True, csrf=new_csrf())
        return {"ok": True, "csrf": request.session["csrf"]}

    @application.post("/api/auth/logout", dependencies=[Depends(require_csrf)])
    def logout(request: Request):
        request.session.clear()
        return {"ok": True}

    @application.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        return page(request, "dashboard.html", page_title="Dashboard", active="dashboard")

    page_routes = {
        "/library": ("library.html", "Music Library", "library"),
        "/search": ("search.html", "Search", "search"),
        "/queue": ("queue.html", "Video Queue", "queue"),
        "/scheduler": ("scheduler.html", "Scheduler", "scheduler"),
        "/completed": ("jobs.html", "Completed Videos", "completed"),
        "/failed": ("jobs.html", "Failed Items", "failed"),
        "/integrations": ("integrations.html", "Plex & Emby", "integrations"),
        "/settings": ("settings.html", "Settings", "settings"),
        "/system": ("system.html", "System Health", "system"),
        "/logs": ("logs.html", "Logs", "logs"),
        "/setup": ("setup.html", "First-run Setup", "setup"),
    }
    for route, (template, title, active) in page_routes.items():
        def handler(request: Request, template=template, title=title, active=active):
            return page(request, template, page_title=title, active=active)
        application.add_api_route(route, handler, methods=["GET"], response_class=HTMLResponse)

    @application.get("/health")
    def health():
        return {"status": "healthy", "version": "2.0.0"}

    @application.get("/ready")
    def ready(request: Request):
        diagnostics = _diagnostics(request, config)
        if not diagnostics["database"]["ok"]:
            return JSONResponse(diagnostics, status_code=503)
        return diagnostics

    @application.get("/api/diagnostics", dependencies=[Depends(require_auth)])
    def diagnostics(request: Request):
        return _diagnostics(request, config)

    @application.get("/api/dashboard", dependencies=[Depends(require_auth)])
    def dashboard_data(request: Request):
        db: Database = request.app.state.database
        with db.connect() as connection:
            tracks = connection.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
            identified = connection.execute(
                "SELECT COUNT(*) FROM tracks WHERE artist!='' AND title!=''"
            ).fetchone()[0]
            artists = connection.execute(
                "SELECT COUNT(DISTINCT artist) FROM tracks WHERE artist!=''"
            ).fetchone()[0]
            jobs = {
                row["state"]: row["count"]
                for row in connection.execute(
                    "SELECT state,COUNT(*) count FROM jobs GROUP BY state"
                )
            }
            activity = [
                dict(row) for row in connection.execute(
                    "SELECT * FROM activity_log ORDER BY id DESC LIMIT 10"
                )
            ]
        scheduler: Scheduler = request.app.state.scheduler
        return {
            "tracks": tracks, "identified": identified, "unidentified": tracks - identified,
            "artists": artists, "jobs": jobs, "downloads_today": scheduler.downloads_today(),
            "daily_limit": scheduler.daily_limit(), "activity": activity,
            "disk": _disk(config.music_video_library), "dry_run": config.dry_run,
        }

    @application.post("/api/library/scan", dependencies=[Depends(require_csrf)])
    def scan(request: Request):
        scanner: LibraryScanner = request.app.state.scanner
        if scanner.status["running"]:
            raise HTTPException(409, "A scan is already running")
        threading.Thread(target=scanner.scan, name="library-scan", daemon=False).start()
        return {"ok": True}

    @application.get("/api/library/status", dependencies=[Depends(require_auth)])
    def scan_status(request: Request):
        return request.app.state.scanner.status

    @application.get("/api/library/tracks", dependencies=[Depends(require_auth)])
    def tracks(
        request: Request, search: str = "", page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200), sort: str = "artist",
    ):
        columns = {"artist": "artist", "album": "album", "title": "title"}
        order = columns.get(sort, "artist")
        offset = (page - 1) * page_size
        with request.app.state.database.connect() as db:
            pattern = f"%{search}%"
            total = db.execute(
                "SELECT COUNT(*) FROM tracks WHERE artist LIKE ? OR album LIKE ? OR title LIKE ?",
                (pattern, pattern, pattern),
            ).fetchone()[0]
            rows = db.execute(
                f"SELECT id,artist,album,title,track_number,duration_seconds,video_status "
                f"FROM tracks WHERE artist LIKE ? OR album LIKE ? OR title LIKE ? "
                f"ORDER BY {order} COLLATE NOCASE LIMIT ? OFFSET ?",
                (pattern, pattern, pattern, page_size, offset),
            ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page}

    @application.get("/api/youtube/search", dependencies=[Depends(require_auth)])
    def youtube_search(
        artist: str = Query(min_length=1, max_length=200),
        title: str = Query(min_length=1, max_length=200),
    ):
        options = {
            "quiet": True, "no_warnings": True, "skip_download": True,
            "extract_flat": True, "playlistend": 8, "socket_timeout": config.external_timeout,
        }
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(
                    f"ytsearch8:{artist} {title} official music video", download=False
                )
            return {
                "items": [
                    {
                        "video_id": item.get("id"), "title": item.get("title"),
                        "channel": item.get("channel") or item.get("uploader") or "",
                        "duration": item.get("duration"), "thumbnail": item.get("thumbnail"),
                    }
                    for item in info.get("entries", []) if item and item.get("id")
                ]
            }
        except Exception as error:
            raise HTTPException(502, f"YouTube search unavailable: {type(error).__name__}") from error

    @application.post("/api/jobs", dependencies=[Depends(require_csrf)])
    def enqueue(payload: QueueRequest, request: Request):
        action_limiter.check(request.client.host if request.client else "unknown")
        try:
            job_id = request.app.state.downloads.enqueue(
                payload.track_id, payload.video_id, payload.dry_run
            )
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return {"ok": True, "job_id": job_id}

    @application.get("/api/jobs", dependencies=[Depends(require_auth)])
    def jobs(request: Request, state: str = "", page: int = Query(1, ge=1)):
        where, args = (" WHERE state=?", [state]) if state else ("", [])
        with request.app.state.database.connect() as db:
            rows = db.execute(
                f"SELECT * FROM jobs{where} ORDER BY id DESC LIMIT 100 OFFSET ?",
                (*args, (page - 1) * 100),
            ).fetchall()
        return {"items": [dict(row) for row in rows], "page": page}

    @application.post("/api/scheduler/start", dependencies=[Depends(require_csrf)])
    def scheduler_start(payload: SchedulerStartRequest, request: Request):
        if not request.app.state.scheduler.start(payload.dry_run):
            raise HTTPException(409, "Scheduler already active or locked by another instance")
        return {"ok": True}

    @application.post("/api/scheduler/pause", dependencies=[Depends(require_csrf)])
    def scheduler_pause(request: Request):
        request.app.state.scheduler.pause()
        return {"ok": True}

    @application.post("/api/scheduler/resume", dependencies=[Depends(require_csrf)])
    def scheduler_resume(request: Request):
        request.app.state.scheduler.resume()
        return {"ok": True}

    @application.post("/api/scheduler/stop-after-current", dependencies=[Depends(require_csrf)])
    def scheduler_stop(request: Request):
        request.app.state.scheduler.stop_after_current()
        return {"ok": True}

    @application.post("/api/scheduler/retry-failed", dependencies=[Depends(require_csrf)])
    def retry_failed(request: Request):
        return {"ok": True, "count": request.app.state.scheduler.retry_failed()}

    @application.get("/api/scheduler/status", dependencies=[Depends(require_auth)])
    def scheduler_status(request: Request):
        scheduler: Scheduler = request.app.state.scheduler
        with request.app.state.database.connect() as db:
            control = dict(db.execute("SELECT * FROM scheduler_control WHERE singleton=1").fetchone())
            progress = [dict(row) for row in db.execute(
                "SELECT artist,state,COUNT(*) count FROM jobs GROUP BY artist,state ORDER BY artist"
            )]
        control["owner"] = bool(control["owner"])
        return {
            "control": control, "downloads_today": scheduler.downloads_today(),
            "daily_limit": scheduler.daily_limit(), "progress": progress,
        }

    @application.get("/api/integrations/status", dependencies=[Depends(require_auth)])
    def integration_status(request: Request):
        with request.app.state.database.connect() as db:
            rows = {row["provider"]: dict(row) for row in db.execute("SELECT * FROM integration_status")}
        return {
            "plex": {"enabled": config.plex_enabled, **rows.get("plex", {})},
            "emby": {"enabled": config.emby_enabled, **rows.get("emby", {})},
        }

    @application.post("/api/integrations/{provider}/test", dependencies=[Depends(require_csrf)])
    def integration_test(provider: str, request: Request):
        if provider not in {"plex", "emby"}:
            raise HTTPException(404, "Unknown integration")
        return request.app.state.integrations.test(provider)

    @application.get("/api/integrations/{provider}/libraries", dependencies=[Depends(require_auth)])
    def integration_libraries(provider: str, request: Request):
        if provider not in {"plex", "emby"}:
            raise HTTPException(404, "Unknown integration")
        try:
            return {"items": request.app.state.integrations.libraries(provider)}
        except Exception as error:
            raise HTTPException(502, f"{provider.title()} unavailable: {type(error).__name__}") from error

    @application.post("/api/integrations/{provider}/refresh", dependencies=[Depends(require_csrf)])
    def integration_refresh(provider: str, request: Request):
        if provider not in {"plex", "emby"}:
            raise HTTPException(404, "Unknown integration")
        return request.app.state.integrations.refresh(provider)

    @application.post("/api/settings", dependencies=[Depends(require_csrf)])
    def save_settings(payload: SettingsRequest, request: Request):
        request.app.state.database.set_setting("daily_limit", str(payload.daily_limit))
        request.app.state.database.set_setting("retry_delay_seconds", str(payload.retry_delay_seconds))
        return {"ok": True}

    @application.get("/api/settings", dependencies=[Depends(require_auth)])
    def get_settings(request: Request):
        db = request.app.state.database
        return {
            "daily_limit": int(db.get_setting("daily_limit", "250")),
            "retry_delay_seconds": float(db.get_setting("retry_delay_seconds", "5")),
            "timezone": config.timezone, "dry_run": config.dry_run,
            "music_library": str(config.music_library),
            "music_video_library": str(config.music_video_library),
            "plex_token": "[CONFIGURED]" if config.plex_token else "",
            "emby_api_key": "[CONFIGURED]" if config.emby_api_key else "",
        }

    return application


def _disk(path: Path) -> dict:
    try:
        usage = shutil.disk_usage(path if path.exists() else path.parent)
        return {"total": usage.total, "free": usage.free, "used": usage.used}
    except OSError:
        return {"total": 0, "free": 0, "used": 0}


def _diagnostics(request: Request, config: Settings) -> dict:
    database_ok = True
    try:
        with request.app.state.database.connect() as db:
            db.execute("SELECT 1").fetchone()
    except Exception:
        database_ok = False
    return {
        "status": "ready" if database_ok else "not_ready",
        "database": {"ok": database_ok},
        "music_library": {"exists": config.music_library.exists(), "read_only_required": True},
        "video_library": {"exists": config.music_video_library.exists(), "disk": _disk(config.music_video_library)},
        "ffmpeg": request.app.state.ffmpeg,
        "timezone": config.timezone,
        "dry_run": config.dry_run,
    }


app = create_app()
