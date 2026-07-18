import os
import sqlite3
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from mutagen import File as MutagenFile

app = FastAPI(title="Music Video Sync")

MUSIC_LIBRARY = Path(os.getenv("MUSIC_LIBRARY", "/music"))
DATABASE_PATH = os.getenv(
    "DATABASE_PATH",
    "/data/music-video-sync.db"
)

AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".m4a", ".aac",
    ".ogg", ".opus", ".wav", ".wma", ".alac"
}

scan_status = {
    "running": False,
    "scanned": 0,
    "identified": 0,
    "unidentified": 0,
    "current_file": "",
    "error": ""
}


def initialise_database():
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE,
                filename TEXT,
                artist TEXT,
                album TEXT,
                title TEXT,
                track_number TEXT,
                duration_seconds REAL,
                extension TEXT,
                video_status TEXT DEFAULT 'not_searched'
            )
        """)
        connection.commit()


def first_tag(tags, names):
    if not tags:
        return ""

    for name in names:
        value = tags.get(name)

        if value:
            if isinstance(value, list):
                return str(value[0]).strip()

            return str(value).strip()

    return ""


def scan_library():
    global scan_status

    if scan_status["running"]:
        return

    scan_status = {
        "running": True,
        "scanned": 0,
        "identified": 0,
        "unidentified": 0,
        "current_file": "",
        "error": ""
    }

    try:
        initialise_database()

        with sqlite3.connect(DATABASE_PATH) as connection:
            for file_path in MUSIC_LIBRARY.rglob("*"):
                if not file_path.is_file():
                    continue

                if file_path.suffix.lower() not in AUDIO_EXTENSIONS:
                    continue

                scan_status["scanned"] += 1
                scan_status["current_file"] = str(file_path)

                artist = ""
                album = ""
                title = ""
                track_number = ""
                duration = 0

                try:
                    audio = MutagenFile(file_path, easy=True)

                    if audio:
                        artist = first_tag(
                            audio.tags,
                            ["artist", "albumartist"]
                        )
                        album = first_tag(audio.tags, ["album"])
                        title = first_tag(audio.tags, ["title"])
                        track_number = first_tag(
                            audio.tags,
                            ["tracknumber"]
                        )

                        if audio.info and audio.info.length:
                            duration = round(audio.info.length, 2)

                except Exception:
                    audio = None

                if artist and title:
                    scan_status["identified"] += 1
                else:
                    scan_status["unidentified"] += 1

                connection.execute("""
                    INSERT INTO tracks (
                        file_path,
                        filename,
                        artist,
                        album,
                        title,
                        track_number,
                        duration_seconds,
                        extension
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(file_path) DO UPDATE SET
                        filename = excluded.filename,
                        artist = excluded.artist,
                        album = excluded.album,
                        title = excluded.title,
                        track_number = excluded.track_number,
                        duration_seconds = excluded.duration_seconds,
                        extension = excluded.extension
                """, (
                    str(file_path),
                    file_path.name,
                    artist,
                    album,
                    title,
                    track_number,
                    duration,
                    file_path.suffix.lower()
                ))

                if scan_status["scanned"] % 100 == 0:
                    connection.commit()

            connection.commit()

    except Exception as error:
        scan_status["error"] = str(error)

    finally:
        scan_status["running"] = False
        scan_status["current_file"] = ""


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return """
    <!doctype html>
    <html>
    <head>
        <title>Music Video Sync</title>
        <style>
            body {
                background: #111318;
                color: #f3f4f6;
                font-family: Arial, sans-serif;
                max-width: 900px;
                margin: 50px auto;
            }
            .panel {
                background: #1c2028;
                border: 1px solid #343b49;
                border-radius: 14px;
                padding: 28px;
            }
            button {
                background: #7c3aed;
                color: white;
                border: 0;
                border-radius: 8px;
                padding: 12px 20px;
                font-size: 16px;
                cursor: pointer;
            }
            .stats {
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 12px;
                margin-top: 22px;
            }
            .stat {
                background: #272c36;
                padding: 18px;
                border-radius: 10px;
            }
            .number {
                font-size: 30px;
                font-weight: bold;
                color: #a78bfa;
            }
            #current {
                color: #9ca3af;
                word-break: break-all;
            }
            #error {
                color: #fb7185;
            }
        </style>
    </head>
    <body>
        <h1>Music Video Sync</h1>

        <div class="panel">
            <p>
                Scan-only safety mode is active.
                No music files will be changed.
            </p>

            <button onclick="startScan()">Scan Music Library</button>

            <div class="stats">
                <div class="stat">
                    <div class="number" id="scanned">0</div>
                    Tracks scanned
                </div>
                <div class="stat">
                    <div class="number" id="identified">0</div>
                    Identified
                </div>
                <div class="stat">
                    <div class="number" id="unidentified">0</div>
                    Missing tags
                </div>
            </div>

            <h3 id="state">Ready</h3>
            <p id="current"></p>
            <p id="error"></p>
        </div>

        <script>
            async function startScan() {
                await fetch("/api/scan", {method: "POST"});
                updateStatus();
            }

            async function updateStatus() {
                const response = await fetch("/api/status");
                const status = await response.json();

                document.getElementById("scanned").textContent =
                    status.scanned;
                document.getElementById("identified").textContent =
                    status.identified;
                document.getElementById("unidentified").textContent =
                    status.unidentified;
                document.getElementById("current").textContent =
                    status.current_file;
                document.getElementById("error").textContent =
                    status.error;
                document.getElementById("state").textContent =
                    status.running ? "Scanning…" : "Ready";

                if (status.running) {
                    setTimeout(updateStatus, 1000);
                }
            }

            updateStatus();
        </script>
    </body>
    </html>
    """


@app.post("/api/scan")
def start_scan():
    if not scan_status["running"]:
        threading.Thread(
            target=scan_library,
            daemon=True
        ).start()

    return {"started": True}


@app.get("/api/status")
def get_status():
    return scan_status


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "music_library": str(MUSIC_LIBRARY),
        "library_exists": MUSIC_LIBRARY.exists()
    }


@app.get("/api/library/summary")
def library_summary():
    initialise_database()

    with sqlite3.connect(DATABASE_PATH) as connection:
        tracks = connection.execute(
            "SELECT COUNT(*) FROM tracks"
        ).fetchone()[0]

        artists = connection.execute(
            """
            SELECT COUNT(DISTINCT artist)
            FROM tracks
            WHERE artist != ''
            """
        ).fetchone()[0]

        albums = connection.execute(
            """
            SELECT COUNT(DISTINCT artist || '|' || album)
            FROM tracks
            WHERE album != ''
            """
        ).fetchone()[0]

    return {
        "tracks": tracks,
        "artists": artists,
        "albums": albums
    }


@app.get("/api/library/artists")
def library_artists():
    initialise_database()

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row

        rows = connection.execute("""
            SELECT
                artist,
                COUNT(*) AS track_count,
                COUNT(DISTINCT album) AS album_count
            FROM tracks
            WHERE artist != ''
            GROUP BY artist
            ORDER BY artist COLLATE NOCASE
        """).fetchall()

    return [dict(row) for row in rows]


@app.get("/api/library/tracks")
def library_tracks(artist: str):
    initialise_database()

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row

        rows = connection.execute("""
            SELECT
                id,
                artist,
                album,
                title,
                track_number,
                filename,
                duration_seconds,
                video_status
            FROM tracks
            WHERE artist = ?
            ORDER BY album COLLATE NOCASE,
                     CAST(track_number AS INTEGER),
                     title COLLATE NOCASE
        """, (artist,)).fetchall()

    return [dict(row) for row in rows]


@app.get("/library", response_class=HTMLResponse)
def library_page():
    return """
    <!doctype html>
    <html>
    <head>
        <title>Music Library - Music Video Sync</title>
        <style>
            body {
                background: #111318;
                color: #f3f4f6;
                font-family: Arial, sans-serif;
                max-width: 1200px;
                margin: 35px auto;
                padding: 0 20px;
            }
            a {
                color: #a78bfa;
            }
            .summary {
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 15px;
                margin: 25px 0;
            }
            .card, .panel {
                background: #1c2028;
                border: 1px solid #343b49;
                border-radius: 12px;
                padding: 20px;
            }
            .number {
                color: #a78bfa;
                font-size: 32px;
                font-weight: bold;
            }
            .layout {
                display: grid;
                grid-template-columns: 360px 1fr;
                gap: 18px;
            }
            .artist {
                padding: 12px;
                border-bottom: 1px solid #343b49;
                cursor: pointer;
            }
            .artist:hover {
                background: #272c36;
            }
            .small {
                color: #9ca3af;
                font-size: 13px;
            }
            .scroll {
                max-height: 650px;
                overflow-y: auto;
            }
            table {
                width: 100%;
                border-collapse: collapse;
            }
            th, td {
                text-align: left;
                padding: 10px;
                border-bottom: 1px solid #343b49;
            }
            th {
                color: #a78bfa;
            }
            input {
                width: calc(100% - 24px);
                background: #272c36;
                color: white;
                border: 1px solid #414959;
                border-radius: 7px;
                padding: 11px;
                margin-bottom: 12px;
            }
        </style>
    </head>
    <body>
        <a href="/">← Scanner</a>
        <h1>Music Library</h1>

        <div class="summary">
            <div class="card">
                <div class="number" id="artistCount">0</div>
                Artists
            </div>
            <div class="card">
                <div class="number" id="albumCount">0</div>
                Albums
            </div>
            <div class="card">
                <div class="number" id="trackCount">0</div>
                Tracks
            </div>
        </div>

        <div class="layout">
            <div class="panel">
                <input
                    id="filter"
                    placeholder="Search artists..."
                    oninput="filterArtists()"
                >
                <div id="artists" class="scroll"></div>
            </div>

            <div class="panel">
                <h2 id="selectedArtist">
                    Select an artist
                </h2>
                <div id="tracks" class="scroll"></div>
            </div>
        </div>

        <script>
            let allArtists = [];

            async function loadSummary() {
                const response = await fetch(
                    "/api/library/summary"
                );
                const summary = await response.json();

                artistCount.textContent = summary.artists;
                albumCount.textContent = summary.albums;
                trackCount.textContent = summary.tracks;
            }

            async function loadArtists() {
                const response = await fetch(
                    "/api/library/artists"
                );

                allArtists = await response.json();
                renderArtists(allArtists);
            }

            function renderArtists(artists) {
                const container =
                    document.getElementById("artists");

                container.innerHTML = artists.map(item => `
                    <div
                        class="artist"
                        onclick='loadTracks(${JSON.stringify(
                            item.artist
                        )})'
                    >
                        <strong>${escapeHtml(item.artist)}</strong>
                        <div class="small">
                            ${item.album_count} albums ·
                            ${item.track_count} tracks
                        </div>
                    </div>
                `).join("");
            }

            function filterArtists() {
                const value = document.getElementById(
                    "filter"
                ).value.toLowerCase();

                renderArtists(
                    allArtists.filter(item =>
                        item.artist.toLowerCase().includes(value)
                    )
                );
            }

            async function loadTracks(artist) {
                selectedArtist.textContent = artist;

                const response = await fetch(
                    "/api/library/tracks?artist=" +
                    encodeURIComponent(artist)
                );

                const tracks = await response.json();

                document.getElementById("tracks").innerHTML = `
                    <table>
                        <thead>
                            <tr>
                                <th>Album</th>
                                <th>#</th>
                                <th>Song</th>
                                <th>Length</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${tracks.map(track => `
                                <tr>
                                    <td>${escapeHtml(track.album)}</td>
                                    <td>${escapeHtml(
                                        track.track_number
                                    )}</td>
                                    <td>${escapeHtml(track.title)}</td>
                                    <td>${formatDuration(
                                        track.duration_seconds
                                    )}</td>
                                </tr>
                            `).join("")}
                        </tbody>
                    </table>
                `;
            }

            function formatDuration(seconds) {
                const total = Math.round(seconds || 0);
                const minutes = Math.floor(total / 60);
                const remaining = String(total % 60).padStart(2, "0");
                return `${minutes}:${remaining}`;
            }

            function escapeHtml(value) {
                const element = document.createElement("div");
                element.textContent = value || "";
                return element.innerHTML;
            }

            loadSummary();
            loadArtists();
        </script>
    </body>
    </html>
    """


import re
import yt_dlp
from fastapi import Query


def normalise_text(value):
    value = (value or "").lower()
    value = value.replace("&", "and")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def score_video(result, artist, title, track_duration):
    video_title = normalise_text(result.get("title"))
    channel = normalise_text(
        result.get("channel") or result.get("uploader")
    )
    wanted_artist = normalise_text(artist)
    wanted_title = normalise_text(title)

    score = 0
    reasons = []

    if wanted_artist and wanted_artist in video_title:
        score += 25
        reasons.append("artist in title")

    if wanted_title and wanted_title in video_title:
        score += 35
        reasons.append("song title matched")

    if wanted_artist and wanted_artist in channel:
        score += 15
        reasons.append("artist channel matched")

    if "official music video" in video_title:
        score += 20
        reasons.append("official music video")

    elif "official video" in video_title:
        score += 15
        reasons.append("official video")

    video_duration = result.get("duration") or 0

    if track_duration and video_duration:
        difference = abs(video_duration - track_duration)

        if difference <= 15:
            score += 10
            reasons.append("duration matched")

        elif difference > 90:
            score -= 15
            reasons.append("duration differs")

    rejected_words = {
        "cover": 30,
        "karaoke": 40,
        "reaction": 40,
        "tutorial": 35,
        "nightcore": 40,
        "sped up": 35,
        "slowed": 30,
        "live": 20,
        "remix": 20
    }

    for word, penalty in rejected_words.items():
        if word in video_title:
            score -= penalty
            reasons.append(f"contains {word}")

    return max(0, min(100, score)), reasons


@app.get("/api/youtube/search")
def search_youtube(
    artist: str = Query(min_length=1),
    title: str = Query(min_length=1),
    duration: float = 0
):
    query = f"{artist} {title} official music video"

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "playlistend": 8
    }

    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            information = downloader.extract_info(
                f"ytsearch8:{query}",
                download=False
            )

        results = []

        for item in information.get("entries", []):
            if not item:
                continue

            score, reasons = score_video(
                item,
                artist,
                title,
                duration
            )

            video_id = item.get("id")

            results.append({
                "video_id": video_id,
                "title": item.get("title"),
                "channel": (
                    item.get("channel") or
                    item.get("uploader") or
                    ""
                ),
                "duration": item.get("duration"),
                "view_count": item.get("view_count"),
                "thumbnail": item.get("thumbnail"),
                "url": (
                    f"https://www.youtube.com/watch?v={video_id}"
                    if video_id else item.get("url")
                ),
                "confidence": score,
                "reasons": reasons
            })

        results.sort(
            key=lambda item: item["confidence"],
            reverse=True
        )

        return {
            "query": query,
            "downloaded": False,
            "results": results
        }

    except Exception as error:
        return {
            "query": query,
            "downloaded": False,
            "results": [],
            "error": str(error)
        }


from difflib import SequenceMatcher


def score_video(result, artist, title, track_duration):
    video_title = normalise_text(result.get("title"))
    channel = normalise_text(
        result.get("channel") or result.get("uploader")
    )
    wanted_artist = normalise_text(artist)
    wanted_title = normalise_text(title)

    score = 0
    reasons = []

    if wanted_artist and wanted_artist in video_title:
        score += 25
        reasons.append("artist in title")

    if wanted_title and wanted_title in video_title:
        score += 35
        reasons.append("song title matched")

    if wanted_artist and wanted_artist == channel:
        score += 20
        reasons.append("exact artist channel")

    elif wanted_artist and wanted_artist in channel:
        score += 12
        reasons.append("artist channel matched")

    if re.search(r"official.*video", video_title):
        score += 20
        reasons.append("official video")

    video_duration = result.get("duration") or 0

    if track_duration and video_duration:
        difference = abs(video_duration - track_duration)

        if difference <= 15:
            score += 10
            reasons.append("duration matched")
        elif difference <= 30:
            score += 5
            reasons.append("duration close")
        elif difference > 90:
            score -= 20
            reasons.append("duration differs")

    views = result.get("view_count") or 0

    if views >= 100_000_000:
        score += 10
        reasons.append("major hit")
    elif views >= 10_000_000:
        score += 7
        reasons.append("popular video")
    elif views >= 1_000_000:
        score += 4
        reasons.append("established video")

    rejected_words = {
        "karaoke": 50,
        "reaction": 45,
        "tutorial": 40,
        "nightcore": 45,
        "sped up": 40,
        "slowed": 35,
        "cover": 35,
        "lyrics": 25,
        "lyric video": 20,
        "live": 30,
        "concert": 30,
        "remix": 25,
        "fan made": 40
    }

    for word, penalty in rejected_words.items():
        if word in video_title:
            score -= penalty
            reasons.append(f"contains {word}")

    return max(0, min(100, score)), reasons


def clean_video_title(value, artist):
    cleaned = normalise_text(value)
    cleaned_artist = normalise_text(artist)

    if cleaned_artist:
        cleaned = cleaned.replace(cleaned_artist, " ")

    unwanted = [
        "official", "music", "video", "4k", "hd",
        "remastered", "lyrics", "lyric", "audio"
    ]

    for word in unwanted:
        cleaned = re.sub(
            rf"\b{re.escape(word)}\b",
            " ",
            cleaned
        )

    return " ".join(cleaned.split())


@app.get("/api/youtube/artist-hits")
def artist_hits(
    artist: str = Query(min_length=1),
    limit: int = Query(default=10, ge=1, le=20)
):
    initialise_database()

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row

        local_tracks = connection.execute("""
            SELECT
                MIN(id) AS id,
                artist,
                album,
                title,
                file_path,
                duration_seconds
            FROM tracks
            WHERE artist = ?
              AND title != ''
            GROUP BY lower(title)
            ORDER BY title COLLATE NOCASE
        """, (artist,)).fetchall()

    if not local_tracks:
        return {
            "artist": artist,
            "hits": [],
            "error": "No local tracks found"
        }

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "playlistend": 30
    }

    query = f"{artist} official music videos"

    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            information = downloader.extract_info(
                f"ytsearch30:{query}",
                download=False
            )

        matches = []
        used_tracks = set()
        used_videos = set()

        for video in information.get("entries", []):
            if not video or not video.get("id"):
                continue

            video_id = video["id"]

            if video_id in used_videos:
                continue

            cleaned_video = clean_video_title(
                video.get("title", ""),
                artist
            )

            best_track = None
            best_ratio = 0

            for track in local_tracks:
                local_title = normalise_text(track["title"])

                ratio = SequenceMatcher(
                    None,
                    local_title,
                    cleaned_video
                ).ratio()

                if local_title in cleaned_video:
                    ratio = max(ratio, 0.92)

                if ratio > best_ratio:
                    best_ratio = ratio
                    best_track = track

            if not best_track or best_ratio < 0.72:
                continue

            track_key = normalise_text(best_track["title"])

            if track_key in used_tracks:
                continue

            confidence, reasons = score_video(
                video,
                artist,
                best_track["title"],
                best_track["duration_seconds"]
            )

            video_title = normalise_text(video.get("title"))

            if any(word in video_title for word in [
                "karaoke", "reaction", "tutorial",
                "cover", "nightcore", "sped up",
                "slowed", "fan made"
            ]):
                continue

            matches.append({
                "track_id": best_track["id"],
                "artist": artist,
                "album": best_track["album"],
                "track_title": best_track["title"],
                "file_path": best_track["file_path"],
                "video_id": video_id,
                "video_title": video.get("title"),
                "channel": (
                    video.get("channel") or
                    video.get("uploader") or ""
                ),
                "duration": video.get("duration"),
                "view_count": video.get("view_count") or 0,
                "confidence": confidence,
                "title_similarity": round(best_ratio * 100),
                "url": (
                    "https://www.youtube.com/watch?v=" +
                    video_id
                ),
                "reasons": reasons
            })

            used_tracks.add(track_key)
            used_videos.add(video_id)

        matches.sort(
            key=lambda item: (
                item["view_count"],
                item["confidence"]
            ),
            reverse=True
        )

        return {
            "artist": artist,
            "query": query,
            "local_unique_tracks": len(local_tracks),
            "hits": matches[:limit],
            "downloaded": False
        }

    except Exception as error:
        return {
            "artist": artist,
            "query": query,
            "hits": [],
            "downloaded": False,
            "error": str(error)
        }


@app.get("/hits", response_class=HTMLResponse)
def hits_page():
    return """
    <!doctype html>
    <html>
    <head>
        <title>Top Hits - Music Video Sync</title>
        <style>
            body {
                background: #111318;
                color: #f3f4f6;
                font-family: Arial, sans-serif;
                max-width: 1250px;
                margin: 35px auto;
                padding: 0 20px;
            }
            a {
                color: #a78bfa;
            }
            .controls, .result {
                background: #1c2028;
                border: 1px solid #343b49;
                border-radius: 12px;
                padding: 20px;
                margin-bottom: 15px;
            }
            .controls {
                display: flex;
                gap: 12px;
                align-items: end;
            }
            label {
                display: block;
                color: #aeb6c5;
                margin-bottom: 6px;
            }
            input, select {
                background: #272c36;
                color: white;
                border: 1px solid #414959;
                border-radius: 7px;
                padding: 11px;
                min-width: 250px;
            }
            select {
                min-width: 100px;
            }
            button {
                background: #7c3aed;
                color: white;
                border: 0;
                border-radius: 8px;
                padding: 12px 20px;
                cursor: pointer;
                font-size: 15px;
            }
            button:disabled {
                opacity: 0.5;
                cursor: wait;
            }
            .result {
                display: grid;
                grid-template-columns: 70px 1fr 180px;
                gap: 18px;
                align-items: center;
            }
            .position {
                color: #a78bfa;
                font-size: 34px;
                font-weight: bold;
                text-align: center;
            }
            .title {
                font-size: 20px;
                font-weight: bold;
                margin-bottom: 5px;
            }
            .video {
                color: #c4b5fd;
                margin-top: 9px;
            }
            .details {
                color: #9ca3af;
                font-size: 14px;
                margin-top: 5px;
            }
            .confidence {
                color: #86efac;
                font-size: 24px;
                font-weight: bold;
            }
            .actions {
                text-align: right;
            }
            .youtube {
                display: inline-block;
                background: #dc2626;
                color: white;
                text-decoration: none;
                padding: 9px 13px;
                border-radius: 7px;
                margin-top: 10px;
            }
            #message {
                color: #c4b5fd;
                margin: 20px 0;
            }
            @media (max-width: 750px) {
                .controls {
                    display: block;
                }
                .controls > div {
                    margin-bottom: 12px;
                }
                .result {
                    grid-template-columns: 50px 1fr;
                }
                .actions {
                    grid-column: 2;
                    text-align: left;
                }
            }
        </style>
    </head>
    <body>
        <nav>
            <a href="/">Scanner</a> ·
            <a href="/library">Library</a>
        </nav>

        <h1>Artist Top Hits</h1>

        <p>
            Searches only for popular videos matching songs already
            present in your music library. Nothing is downloaded.
        </p>

        <div class="controls">
            <div>
                <label for="artist">Artist</label>
                <input
                    id="artist"
                    list="artistList"
                    placeholder="Start typing an artist..."
                >
                <datalist id="artistList"></datalist>
            </div>

            <div>
                <label for="limit">Number of hits</label>
                <select id="limit">
                    <option value="5">Top 5</option>
                    <option value="10" selected>Top 10</option>
                    <option value="20">Top 20</option>
                </select>
            </div>

            <button id="searchButton" onclick="findHits()">
                Find Top Hits
            </button>
        </div>

        <div id="message"></div>
        <div id="results"></div>

        <script>
            async function loadArtists() {
                const response = await fetch(
                    "/api/library/artists"
                );

                const artists = await response.json();

                document.getElementById(
                    "artistList"
                ).innerHTML = artists.map(item =>
                    `<option value="${escapeHtml(
                        item.artist
                    )}"></option>`
                ).join("");
            }

            async function findHits() {
                const artist = document.getElementById(
                    "artist"
                ).value.trim();

                const limit = document.getElementById(
                    "limit"
                ).value;

                if (!artist) {
                    message.textContent =
                        "Choose or enter an artist.";
                    return;
                }

                const button = document.getElementById(
                    "searchButton"
                );

                button.disabled = true;
                button.textContent = "Searching…";
                message.textContent =
                    `Searching official videos for ${artist}…`;
                results.innerHTML = "";

                try {
                    const response = await fetch(
                        "/api/youtube/artist-hits?artist=" +
                        encodeURIComponent(artist) +
                        "&limit=" + limit
                    );

                    const data = await response.json();

                    if (data.error) {
                        throw new Error(data.error);
                    }

                    message.textContent =
                        `Found ${data.hits.length} matching hits ` +
                        `from ${data.local_unique_tracks} unique ` +
                        `local tracks. No files downloaded.`;

                    renderResults(data.hits);

                } catch (error) {
                    message.textContent =
                        "Search failed: " + error.message;

                } finally {
                    button.disabled = false;
                    button.textContent = "Find Top Hits";
                }
            }

            function renderResults(hits) {
                const container = document.getElementById(
                    "results"
                );

                if (!hits.length) {
                    container.innerHTML =
                        "<p>No reliable matches were found.</p>";
                    return;
                }

                container.innerHTML = hits.map(
                    (hit, index) => `
                    <div class="result">
                        <div class="position">
                            ${index + 1}
                        </div>

                        <div>
                            <div class="title">
                                ${escapeHtml(hit.track_title)}
                            </div>

                            <div>
                                ${escapeHtml(hit.album)}
                            </div>

                            <div class="video">
                                ${escapeHtml(hit.video_title)}
                            </div>

                            <div class="details">
                                ${escapeHtml(hit.channel)} ·
                                ${formatNumber(hit.view_count)} views ·
                                ${formatDuration(hit.duration)}
                            </div>
                        </div>

                        <div class="actions">
                            <div class="confidence">
                                ${hit.confidence}%
                            </div>
                            confidence
                            <br>
                            <a
                                class="youtube"
                                href="${hit.url}"
                                target="_blank"
                                rel="noopener"
                            >
                                Preview on YouTube
                            </a>
                        </div>
                    </div>
                `).join("");
            }

            function formatNumber(number) {
                return new Intl.NumberFormat().format(
                    number || 0
                );
            }

            function formatDuration(seconds) {
                const total = Math.round(seconds || 0);
                const minutes = Math.floor(total / 60);
                const remaining = String(
                    total % 60
                ).padStart(2, "0");

                return `${minutes}:${remaining}`;
            }

            function escapeHtml(value) {
                const element = document.createElement("div");
                element.textContent = value || "";
                return element.innerHTML;
            }

            loadArtists();
        </script>
    </body>
    </html>
    """


from pydantic import BaseModel


from pydantic import BaseModel


STAGING_PATH = Path("/data/staging")
ALLOW_STAGING_DOWNLOADS = (
    os.getenv("ALLOW_STAGING_DOWNLOADS", "false").lower()
    == "true"
)


class StagingDownloadRequest(BaseModel):
    track_id: int
    video_id: str


def staging_safe_filename(value):
    value = re.sub(r'[<>:"/\\\\|?*]', "_", value)
    return value.rstrip(" .")[:180]


@app.post("/api/youtube/download")
def staging_download(request: StagingDownloadRequest):
    if not ALLOW_STAGING_DOWNLOADS:
        return {
            "success": False,
            "error": "Staging downloads are disabled"
        }

    if not re.fullmatch(
        r"[A-Za-z0-9_-]{11}",
        request.video_id
    ):
        return {
            "success": False,
            "error": "Invalid video ID"
        }

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row

        track = connection.execute("""
            SELECT
                id,
                artist,
                album,
                title,
                filename,
                file_path
            FROM tracks
            WHERE id = ?
        """, (request.track_id,)).fetchone()

    if not track:
        return {
            "success": False,
            "error": "Track not found"
        }

    folder = STAGING_PATH / str(track["id"])
    folder.mkdir(parents=True, exist_ok=True)

    audio_stem = Path(track["filename"]).stem

    final_name = staging_safe_filename(
        audio_stem +
        " - Official Music Video-video.mp4"
    )

    final_path = folder / final_name

    if final_path.exists():
        return {
            "success": True,
            "already_downloaded": True,
            "staging_path": str(final_path),
            "size_bytes": final_path.stat().st_size,
            "music_library_modified": False
        }

    output_template = str(
        folder / f"{request.video_id}.%(ext)s"
    )

    options = {
        "format": (
            "bv*[height<=1080]+ba/"
            "b[height<=1080]/best"
        ),
        "merge_output_format": "mp4",
        "outtmpl": output_template,
        "noplaylist": True,
        "retries": 3,
        "fragment_retries": 3,
        "continuedl": True
    }

    url = (
        "https://www.youtube.com/watch?v=" +
        request.video_id
    )

    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.download([url])

        candidates = [
            item for item in folder.glob(
                request.video_id + ".*"
            )
            if item.suffix.lower() in {
                ".mp4", ".mkv", ".webm", ".mov"
            }
        ]

        if not candidates:
            return {
                "success": False,
                "error": "Downloaded video file was not found"
            }

        downloaded = max(
            candidates,
            key=lambda item: item.stat().st_size
        )

        downloaded.replace(final_path)

        return {
            "success": True,
            "already_downloaded": False,
            "artist": track["artist"],
            "album": track["album"],
            "track": track["title"],
            "staging_path": str(final_path),
            "size_bytes": final_path.stat().st_size,
            "music_library_modified": False
        }

    except Exception as error:
        return {
            "success": False,
            "track": track["title"],
            "video_id": request.video_id,
            "error": str(error)
        }


import shutil
import subprocess
from datetime import datetime, timezone


MUSIC_VIDEO_LIBRARY = Path(
    os.getenv("MUSIC_VIDEO_LIBRARY", "/music-videos")
)

VIDEO_QUALITY = int(
    os.getenv("VIDEO_QUALITY", "720")
)


class ProductionRequest(BaseModel):
    track_id: int
    video_id: str


def production_safe_name(value):
    value = re.sub(r'[<>:"/\\\\|?*]', "_", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.rstrip(" .")[:150] or "Unknown"


def initialise_video_downloads():
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS video_downloads (
                track_id INTEGER PRIMARY KEY,
                video_id TEXT NOT NULL,
                artist TEXT NOT NULL,
                title TEXT NOT NULL,
                destination TEXT NOT NULL,
                quality INTEGER NOT NULL,
                status TEXT NOT NULL,
                size_bytes INTEGER,
                completed_at TEXT
            )
        """)
        connection.commit()


@app.post("/api/music-videos/process")
def process_music_video(request: ProductionRequest):
    if not ALLOW_STAGING_DOWNLOADS:
        return {
            "success": False,
            "error": "Production processing is disabled"
        }

    if not re.fullmatch(
        r"[A-Za-z0-9_-]{11}",
        request.video_id
    ):
        return {
            "success": False,
            "error": "Invalid YouTube video ID"
        }

    initialise_video_downloads()

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row

        track = connection.execute("""
            SELECT
                id,
                artist,
                album,
                title,
                filename,
                file_path,
                duration_seconds
            FROM tracks
            WHERE id = ?
        """, (request.track_id,)).fetchone()

    if not track:
        return {
            "success": False,
            "error": "Local track was not found"
        }

    artist_name = production_safe_name(track["artist"])
    title_name = production_safe_name(track["title"])

    artist_folder = MUSIC_VIDEO_LIBRARY / artist_name

    destination = (
        artist_folder /
        f"{artist_name} - {title_name}.mp4"
    )

    if destination.exists():
        return {
            "success": True,
            "already_exists": True,
            "artist": track["artist"],
            "track": track["title"],
            "destination": str(destination),
            "size_bytes": destination.stat().st_size
        }

    work_folder = (
        Path("/data/processing") /
        str(track["id"])
    )

    work_folder.mkdir(parents=True, exist_ok=True)

    for old_file in work_folder.glob("*"):
        if old_file.is_file():
            old_file.unlink()

    download_template = str(
        work_folder / (
            request.video_id + ".%(ext)s"
        )
    )

    download_options = {
        "format": (
            f"bv*[height<={VIDEO_QUALITY}]"
            "[vcodec^=avc1]+ba[acodec^=mp4a]/"
            f"b[height<={VIDEO_QUALITY}]"
            "[ext=mp4][vcodec^=avc1][acodec^=mp4a]"
        ),
        "merge_output_format": "mp4",
        "outtmpl": download_template,
        "noplaylist": True,
        "retries": 3,
        "fragment_retries": 3,
        "continuedl": True
    }

    video_url = (
        "https://www.youtube.com/watch?v=" +
        request.video_id
    )

    try:
        with yt_dlp.YoutubeDL(
            download_options
        ) as downloader:
            downloader.download([video_url])

        candidates = [
            candidate
            for candidate in work_folder.glob("*")
            if candidate.is_file()
            and candidate.suffix.lower() in {
                ".mp4", ".mkv", ".webm", ".mov"
            }
        ]

        if not candidates:
            raise RuntimeError(
                "The downloaded video was not found"
            )

        downloaded = max(
            candidates,
            key=lambda item: item.stat().st_size
        )

        converted = work_folder / "converted.mp4"

        conversion_command = [
            "ffmpeg",
            "-y",
            "-i", str(downloaded),
            "-map", "0:v:0",
            "-map", "0:a:0",
            "-c:v", "copy",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(converted)
        ]

        conversion = subprocess.run(
            conversion_command,
            capture_output=True,
            text=True
        )

        if conversion.returncode != 0:
            raise RuntimeError(
                "FFmpeg conversion failed: " +
                conversion.stderr[-2000:]
            )

        if not converted.exists():
            raise RuntimeError(
                "Compatible MP4 was not created"
            )

        artist_folder.mkdir(
            parents=True,
            exist_ok=True
        )

        shutil.move(
            str(converted),
            str(destination)
        )

        completed = datetime.now(
            timezone.utc
        ).isoformat()

        with sqlite3.connect(
            DATABASE_PATH
        ) as connection:
            connection.execute("""
                INSERT INTO video_downloads (
                    track_id,
                    video_id,
                    artist,
                    title,
                    destination,
                    quality,
                    status,
                    size_bytes,
                    completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(track_id) DO UPDATE SET
                    video_id = excluded.video_id,
                    destination = excluded.destination,
                    quality = excluded.quality,
                    status = excluded.status,
                    size_bytes = excluded.size_bytes,
                    completed_at = excluded.completed_at
            """, (
                track["id"],
                request.video_id,
                track["artist"],
                track["title"],
                str(destination),
                VIDEO_QUALITY,
                "completed",
                destination.stat().st_size,
                completed
            ))

            connection.commit()

        return {
            "success": True,
            "already_exists": False,
            "artist": track["artist"],
            "album": track["album"],
            "track": track["title"],
            "quality": VIDEO_QUALITY,
            "video_codec": "h264",
            "audio_codec": "aac",
            "destination": str(destination),
            "size_bytes": destination.stat().st_size,
            "music_library_modified": False
        }

    except Exception as error:
        return {
            "success": False,
            "artist": track["artist"],
            "track": track["title"],
            "video_id": request.video_id,
            "error": str(error)
        }



@app.get("/production", response_class=HTMLResponse)
def production_page():
    return """
    <!doctype html>
    <html>
    <head>
        <title>Music Video Production</title>
        <style>
            body {
                background: #111318;
                color: #f3f4f6;
                font-family: Arial, sans-serif;
                max-width: 1250px;
                margin: 35px auto;
                padding: 0 20px;
            }
            a {
                color: #a78bfa;
            }
            .controls, .result {
                background: #1c2028;
                border: 1px solid #343b49;
                border-radius: 12px;
                padding: 20px;
                margin-bottom: 14px;
            }
            .controls {
                display: flex;
                gap: 12px;
                align-items: end;
            }
            label {
                display: block;
                color: #9ca3af;
                margin-bottom: 6px;
            }
            input, select {
                background: #272c36;
                color: white;
                border: 1px solid #414959;
                border-radius: 7px;
                padding: 11px;
            }
            input {
                min-width: 280px;
            }
            button {
                background: #7c3aed;
                color: white;
                border: 0;
                border-radius: 8px;
                padding: 11px 16px;
                cursor: pointer;
            }
            button:disabled {
                opacity: 0.5;
                cursor: wait;
            }
            .result {
                display: grid;
                grid-template-columns: 55px 1fr 245px;
                gap: 16px;
                align-items: center;
            }
            .rank {
                color: #a78bfa;
                font-size: 30px;
                font-weight: bold;
                text-align: center;
            }
            .song {
                font-size: 20px;
                font-weight: bold;
            }
            .video {
                color: #c4b5fd;
                margin-top: 7px;
            }
            .details, .status {
                color: #9ca3af;
                margin-top: 6px;
                font-size: 14px;
            }
            .actions {
                text-align: right;
            }
            .preview {
                display: inline-block;
                background: #dc2626;
                color: white;
                text-decoration: none;
                border-radius: 7px;
                padding: 10px 13px;
                margin-bottom: 8px;
            }
            .download {
                background: #16a34a;
            }
            .success {
                color: #86efac;
            }
            .failure {
                color: #fb7185;
            }
            #message {
                margin: 18px 0;
                color: #c4b5fd;
            }
        </style>
    </head>
    <body>
        <nav>
            <a href="/">Scanner</a> ·
            <a href="/library">Library</a> ·
            <a href="/hits">Top Hits</a>
        </nav>

        <h1>Music Video Production</h1>

        <p>
            Approved videos are produced as 720p H.264/AAC MP4
            files and placed in the Music Videos library.
        </p>

        <div class="controls">
            <div>
                <label>Artist</label>
                <input
                    id="artist"
                    list="artistList"
                    placeholder="Choose an artist..."
                >
                <datalist id="artistList"></datalist>
            </div>

            <div>
                <label>Hits</label>
                <select id="limit">
                    <option value="5">Top 5</option>
                    <option value="10" selected>Top 10</option>
                    <option value="20">Top 20</option>
                </select>
            </div>

            <button id="findButton" onclick="findHits()">
                Find Hits
            </button>
        </div>

        <div id="message"></div>
        <div id="results"></div>

        <script>
            let currentHits = [];

            async function loadArtists() {
                const response = await fetch(
                    "/api/library/artists"
                );

                const artists = await response.json();

                artistList.innerHTML = artists.map(item =>
                    `<option value="${escapeHtml(
                        item.artist
                    )}"></option>`
                ).join("");
            }

            async function findHits() {
                const artistName = artist.value.trim();

                if (!artistName) {
                    message.textContent = "Select an artist.";
                    return;
                }

                findButton.disabled = true;
                findButton.textContent = "Searching…";
                message.textContent =
                    `Searching ${artistName}…`;
                results.innerHTML = "";

                try {
                    const response = await fetch(
                        "/api/youtube/artist-hits?artist=" +
                        encodeURIComponent(artistName) +
                        "&limit=" + limit.value
                    );

                    const data = await response.json();

                    if (data.error) {
                        throw new Error(data.error);
                    }

                    currentHits = data.hits;

                    message.textContent =
                        `Found ${currentHits.length} matches. ` +
                        `Review each result before downloading.`;

                    renderHits();

                } catch (error) {
                    message.textContent =
                        "Search failed: " + error.message;

                } finally {
                    findButton.disabled = false;
                    findButton.textContent = "Find Hits";
                }
            }

            function renderHits() {
                results.innerHTML = currentHits.map(
                    (hit, index) => `
                    <div class="result">
                        <div class="rank">${index + 1}</div>

                        <div>
                            <div class="song">
                                ${escapeHtml(hit.track_title)}
                            </div>
                            <div>${escapeHtml(hit.album)}</div>
                            <div class="video">
                                ${escapeHtml(hit.video_title)}
                            </div>
                            <div class="details">
                                ${escapeHtml(hit.channel)} ·
                                ${formatNumber(hit.view_count)} views ·
                                ${hit.confidence}% confidence
                            </div>
                            <div
                                class="status"
                                id="status-${index}"
                            ></div>
                        </div>

                        <div class="actions">
                            <a
                                class="preview"
                                href="${hit.url}"
                                target="_blank"
                                rel="noopener"
                            >
                                Preview
                            </a>
                            <br>
                            <button
                                class="download"
                                id="download-${index}"
                                onclick="processHit(${index})"
                            >
                                Approve & Download 720p
                            </button>
                        </div>
                    </div>
                `).join("");
            }

            async function processHit(index) {
                const hit = currentHits[index];
                const button = document.getElementById(
                    `download-${index}`
                );
                const status = document.getElementById(
                    `status-${index}`
                );

                if (!confirm(
                    `Download and process ${hit.track_title}?`
                )) {
                    return;
                }

                button.disabled = true;
                button.textContent = "Processing…";
                status.className = "status";
                status.textContent =
                    "Downloading and converting. Please wait…";

                try {
                    const response = await fetch(
                        "/api/music-videos/process",
                        {
                            method: "POST",
                            headers: {
                                "Content-Type": "application/json"
                            },
                            body: JSON.stringify({
                                track_id: hit.track_id,
                                video_id: hit.video_id
                            })
                        }
                    );

                    const result = await response.json();

                    if (!result.success) {
                        throw new Error(
                            result.error || "Processing failed"
                        );
                    }

                    status.className = "status success";

                    if (result.already_exists) {
                        status.textContent =
                            "Already exists: " +
                            result.destination;
                    } else {
                        status.textContent =
                            "Completed: " +
                            result.destination;
                    }

                    button.textContent = "Completed";

                } catch (error) {
                    status.className = "status failure";
                    status.textContent =
                        "Failed: " + error.message;
                    button.disabled = false;
                    button.textContent =
                        "Retry Download";

                }
            }

            function formatNumber(number) {
                return new Intl.NumberFormat().format(
                    number || 0
                );
            }

            function escapeHtml(value) {
                const element = document.createElement("div");
                element.textContent = value || "";
                return element.innerHTML;
            }

            loadArtists();
        </script>
    </body>
    </html>
    """


class ArtistBatchRequest(BaseModel):
    artist: str
    limit: int = 10


batch_status = {
    "running": False,
    "artist": "",
    "limit": 10,
    "stage": "idle",
    "total": 0,
    "position": 0,
    "completed": 0,
    "already_exists": 0,
    "failed": 0,
    "current_track": "",
    "current_video": "",
    "stop_requested": False,
    "error": "",
    "items": []
}


def run_artist_batch(artist, limit):
    global batch_status

    batch_status = {
        "running": True,
        "artist": artist,
        "limit": limit,
        "stage": "searching",
        "total": 0,
        "position": 0,
        "completed": 0,
        "already_exists": 0,
        "failed": 0,
        "current_track": "",
        "current_video": "",
        "stop_requested": False,
        "error": "",
        "items": []
    }

    try:
        search_result = artist_hits(
            artist=artist,
            limit=limit
        )

        if search_result.get("error"):
            raise RuntimeError(search_result["error"])

        hits = search_result.get("hits", [])
        batch_status["total"] = len(hits)
        batch_status["stage"] = "processing"

        for position, hit in enumerate(hits, start=1):
            if batch_status["stop_requested"]:
                batch_status["stage"] = "stopped"
                break

            batch_status["position"] = position
            batch_status["current_track"] = (
                hit["track_title"]
            )
            batch_status["current_video"] = (
                hit["video_title"]
            )

            item_status = {
                "position": position,
                "track": hit["track_title"],
                "video": hit["video_title"],
                "video_id": hit["video_id"],
                "confidence": hit["confidence"],
                "status": "processing",
                "message": ""
            }

            batch_status["items"].append(
                item_status
            )

            result = process_music_video(
                ProductionRequest(
                    track_id=hit["track_id"],
                    video_id=hit["video_id"]
                )
            )

            if result.get("success"):
                if result.get("already_exists"):
                    item_status["status"] = (
                        "already_exists"
                    )
                    item_status["message"] = (
                        result.get("destination", "")
                    )
                    batch_status["already_exists"] += 1
                else:
                    item_status["status"] = "completed"
                    item_status["message"] = (
                        result.get("destination", "")
                    )
                    batch_status["completed"] += 1
            else:
                item_status["status"] = "failed"
                item_status["message"] = result.get(
                    "error",
                    "Unknown processing error"
                )
                batch_status["failed"] += 1

        if batch_status["stage"] != "stopped":
            batch_status["stage"] = "completed"

    except Exception as error:
        batch_status["stage"] = "failed"
        batch_status["error"] = str(error)

    finally:
        batch_status["running"] = False
        batch_status["current_track"] = ""
        batch_status["current_video"] = ""


@app.post("/api/music-videos/batch/start")
def start_artist_batch(request: ArtistBatchRequest):
    if batch_status["running"]:
        return {
            "success": False,
            "error": (
                "Another artist batch is already running"
            ),
            "status": batch_status
        }

    artist = request.artist.strip()
    limit = max(1, min(20, request.limit))

    if not artist:
        return {
            "success": False,
            "error": "Artist is required"
        }

    threading.Thread(
        target=run_artist_batch,
        args=(artist, limit),
        daemon=True
    ).start()

    return {
        "success": True,
        "message": f"Started Top {limit} for {artist}"
    }


@app.get("/api/music-videos/batch/status")
def get_artist_batch_status():
    return batch_status


@app.post("/api/music-videos/batch/stop")
def stop_artist_batch():
    if not batch_status["running"]:
        return {
            "success": False,
            "message": "No batch is currently running"
        }

    batch_status["stop_requested"] = True

    return {
        "success": True,
        "message": (
            "The queue will stop after the current "
            "video finishes"
        )
    }


@app.get("/queue", response_class=HTMLResponse)
def queue_page():
    return """
    <!doctype html>
    <html>
    <head>
        <title>Music Video Queue</title>
        <style>
            body {
                background: #111318;
                color: #f3f4f6;
                font-family: Arial, sans-serif;
                max-width: 1150px;
                margin: 35px auto;
                padding: 0 20px;
            }
            a {
                color: #a78bfa;
            }
            .panel, .item {
                background: #1c2028;
                border: 1px solid #343b49;
                border-radius: 12px;
                padding: 20px;
                margin-bottom: 14px;
            }
            .controls {
                display: flex;
                gap: 12px;
                align-items: end;
            }
            label {
                display: block;
                color: #9ca3af;
                margin-bottom: 6px;
            }
            input, select {
                background: #272c36;
                color: white;
                border: 1px solid #414959;
                border-radius: 7px;
                padding: 11px;
            }
            input {
                min-width: 280px;
            }
            button {
                color: white;
                border: 0;
                border-radius: 8px;
                padding: 12px 18px;
                cursor: pointer;
            }
            button:disabled {
                opacity: 0.5;
                cursor: wait;
            }
            #startButton {
                background: #16a34a;
            }
            #stopButton {
                background: #dc2626;
            }
            .progress-shell {
                height: 22px;
                background: #272c36;
                border-radius: 12px;
                overflow: hidden;
                margin: 18px 0;
            }
            .progress-bar {
                height: 100%;
                width: 0;
                background: #7c3aed;
                transition: width 0.4s;
            }
            .stats {
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 12px;
            }
            .stat {
                background: #272c36;
                padding: 15px;
                border-radius: 9px;
            }
            .number {
                font-size: 26px;
                font-weight: bold;
                color: #a78bfa;
            }
            .item {
                display: grid;
                grid-template-columns: 50px 1fr 150px;
                gap: 14px;
            }
            .position {
                color: #a78bfa;
                font-size: 26px;
                font-weight: bold;
            }
            .video {
                color: #9ca3af;
                margin-top: 4px;
            }
            .completed {
                color: #86efac;
            }
            .already_exists {
                color: #93c5fd;
            }
            .failed {
                color: #fb7185;
            }
            .processing {
                color: #facc15;
            }
            #current {
                color: #c4b5fd;
                min-height: 24px;
            }
            #error {
                color: #fb7185;
            }
        </style>
    </head>
    <body>
        <nav>
            <a href="/">Scanner</a> ·
            <a href="/library">Library</a> ·
            <a href="/production">Production</a>
        </nav>

        <h1>Artist Download Queue</h1>

        <p>
            Processes one approved official match at a time.
            Existing files are skipped automatically.
        </p>

        <div class="panel">
            <div class="controls">
                <div>
                    <label>Artist</label>
                    <input
                        id="artist"
                        list="artistList"
                        placeholder="Choose an artist..."
                    >
                    <datalist id="artistList"></datalist>
                </div>

                <div>
                    <label>Number of hits</label>
                    <select id="limit">
                        <option value="5">Top 5</option>
                        <option value="10" selected>Top 10</option>
                        <option value="20">Top 20</option>
                    </select>
                </div>

                <button
                    id="startButton"
                    onclick="startQueue()"
                >
                    Process Artist
                </button>

                <button
                    id="stopButton"
                    onclick="stopQueue()"
                    disabled
                >
                    Stop After Current
                </button>
            </div>

            <div class="progress-shell">
                <div
                    id="progressBar"
                    class="progress-bar"
                ></div>
            </div>

            <h3 id="stage">Idle</h3>
            <div id="current"></div>
            <div id="error"></div>

            <div class="stats">
                <div class="stat">
                    <div class="number" id="position">0</div>
                    Position
                </div>
                <div class="stat">
                    <div class="number" id="completed">0</div>
                    Downloaded
                </div>
                <div class="stat">
                    <div class="number" id="existing">0</div>
                    Already existed
                </div>
                <div class="stat">
                    <div class="number" id="failed">0</div>
                    Failed
                </div>
            </div>
        </div>

        <div id="items"></div>

        <script>
            let pollingTimer = null;

            async function loadArtists() {
                const response = await fetch(
                    "/api/library/artists"
                );
                const artists = await response.json();

                artistList.innerHTML = artists.map(item =>
                    `<option value="${escapeHtml(
                        item.artist
                    )}"></option>`
                ).join("");
            }

            async function startQueue() {
                const artistName = artist.value.trim();

                if (!artistName) {
                    alert("Choose an artist.");
                    return;
                }

                if (!confirm(
                    `Process the ${limit.options[
                        limit.selectedIndex
                    ].text} for ${artistName}?`
                )) {
                    return;
                }

                const response = await fetch(
                    "/api/music-videos/batch/start",
                    {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({
                            artist: artistName,
                            limit: Number(limit.value)
                        })
                    }
                );

                const result = await response.json();

                if (!result.success) {
                    alert(result.error || result.message);
                    return;
                }

                items.innerHTML = "";
                pollStatus();
            }

            async function stopQueue() {
                await fetch(
                    "/api/music-videos/batch/stop",
                    {method: "POST"}
                );

                stopButton.disabled = true;
                current.textContent =
                    "Stopping after the current video…";
            }

            async function pollStatus() {
                clearTimeout(pollingTimer);

                try {
                    const response = await fetch(
                        "/api/music-videos/batch/status"
                    );
                    const status = await response.json();

                    renderStatus(status);

                    if (status.running) {
                        pollingTimer = setTimeout(
                            pollStatus,
                            1500
                        );
                    }

                } catch (problem) {
                    error.textContent =
                        "Status check failed: " +
                        problem.message;

                    pollingTimer = setTimeout(
                        pollStatus,
                        3000
                    );
                }
            }

            function renderStatus(status) {
                stage.textContent =
                    status.stage.toUpperCase();

                position.textContent =
                    `${status.position}/${status.total}`;
                completed.textContent = status.completed;
                existing.textContent =
                    status.already_exists;
                failed.textContent = status.failed;

                const percentage = status.total
                    ? Math.round(
                        status.position /
                        status.total * 100
                    )
                    : 0;

                progressBar.style.width =
                    `${percentage}%`;

                current.textContent =
                    status.current_track
                    ? `Processing: ${status.current_track}`
                    : "";

                error.textContent = status.error || "";

                startButton.disabled = status.running;
                stopButton.disabled = !status.running;

                items.innerHTML = status.items.map(item => `
                    <div class="item">
                        <div class="position">
                            ${item.position}
                        </div>
                        <div>
                            <strong>
                                ${escapeHtml(item.track)}
                            </strong>
                            <div class="video">
                                ${escapeHtml(item.video)}
                            </div>
                            <div class="${item.status}">
                                ${escapeHtml(item.message)}
                            </div>
                        </div>
                        <div class="${item.status}">
                            ${formatStatus(item.status)}
                        </div>
                    </div>
                `).join("");
            }

            function formatStatus(value) {
                const labels = {
                    processing: "Processing…",
                    completed: "Downloaded",
                    already_exists: "Already exists",
                    failed: "Failed"
                };

                return labels[value] || value;
            }

            function escapeHtml(value) {
                const element = document.createElement("div");
                element.textContent = value || "";
                return element.innerHTML;
            }

            loadArtists();
            pollStatus();
        </script>
    </body>
    </html>
    """




def scheduler_exclusion_reason(
    artist,
    track_count,
    minimum_tracks
):
    normalised = (
        " " +
        normalise_text(artist) +
        " "
    )

    if track_count < minimum_tracks:
        return "not enough local tracks"

    featured_patterns = [
        " feat ",
        " featuring ",
        " ft ",
        " versus ",
        " vs "
    ]

    if any(
        pattern in normalised
        for pattern in featured_patterns
    ):
        return "featured or collaboration tag"

    return ""


@app.get("/api/scheduler/preview")
def scheduler_preview(
    minimum_tracks: int = Query(
        default=5,
        ge=1,
        le=100
    ),
    hits_per_artist: int = Query(
        default=10,
        ge=1,
        le=20
    )
):
    initialise_database()

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row

        rows = connection.execute("""
            SELECT
                artist,
                COUNT(*) AS track_count,
                COUNT(DISTINCT lower(title))
                    AS unique_track_count,
                COUNT(DISTINCT album)
                    AS album_count
            FROM tracks
            WHERE artist != ''
            GROUP BY artist
            ORDER BY artist COLLATE NOCASE
        """).fetchall()

    eligible = []
    excluded = []

    for row in rows:
        artist = row["artist"]
        unique_tracks = row["unique_track_count"]

        reason = scheduler_exclusion_reason(
            artist,
            unique_tracks,
            minimum_tracks
        )

        item = {
            "artist": artist,
            "track_count": row["track_count"],
            "unique_tracks": unique_tracks,
            "albums": row["album_count"]
        }

        if reason:
            item["reason"] = reason
            excluded.append(item)
        else:
            eligible.append(item)

    maximum_videos = (
        len(eligible) *
        hits_per_artist
    )

    estimated_average_mb = 76
    estimated_storage_mb = (
        maximum_videos *
        estimated_average_mb
    )

    return {
        "settings": {
            "minimum_tracks": minimum_tracks,
            "hits_per_artist": hits_per_artist,
            "estimated_average_video_mb":
                estimated_average_mb
        },
        "total_artist_tags": len(rows),
        "eligible_artist_count": len(eligible),
        "excluded_artist_count": len(excluded),
        "maximum_possible_videos": maximum_videos,
        "estimated_storage_gb": round(
            estimated_storage_mb / 1024,
            1
        ),
        "eligible_artists": eligible,
        "excluded_artists": excluded,
        "downloads_started": False
    }


class SchedulerPrepareRequest(BaseModel):
    minimum_tracks: int = 10
    hits_per_artist: int = 10
    daily_limit: int = 50


def initialise_scheduler_database():
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS scheduler_artists (
                artist TEXT PRIMARY KEY,
                unique_tracks INTEGER NOT NULL,
                album_count INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                hits_requested INTEGER NOT NULL DEFAULT 10,
                downloaded INTEGER NOT NULL DEFAULT 0,
                already_exists INTEGER NOT NULL DEFAULT 0,
                failed INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS scheduler_settings (
                setting TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        connection.commit()


def scheduler_set_setting(
    connection,
    setting,
    value
):
    connection.execute("""
        INSERT INTO scheduler_settings (
            setting,
            value
        )
        VALUES (?, ?)
        ON CONFLICT(setting) DO UPDATE SET
            value = excluded.value
    """, (setting, str(value)))


@app.post("/api/scheduler/prepare")
def prepare_scheduler(
    request: SchedulerPrepareRequest
):
    initialise_scheduler_database()

    minimum_tracks = max(
        1,
        min(100, request.minimum_tracks)
    )

    hits_per_artist = max(
        1,
        min(20, request.hits_per_artist)
    )

    daily_limit = max(
        1,
        min(500, request.daily_limit)
    )

    preview = scheduler_preview(
        minimum_tracks=minimum_tracks,
        hits_per_artist=hits_per_artist
    )

    now = datetime.now(
        timezone.utc
    ).isoformat()

    added = 0
    retained = 0

    with sqlite3.connect(DATABASE_PATH) as connection:
        for artist in preview["eligible_artists"]:
            existing = connection.execute("""
                SELECT status
                FROM scheduler_artists
                WHERE artist = ?
            """, (artist["artist"],)).fetchone()

            if existing:
                connection.execute("""
                    UPDATE scheduler_artists
                    SET
                        unique_tracks = ?,
                        album_count = ?,
                        hits_requested = ?,
                        updated_at = ?
                    WHERE artist = ?
                """, (
                    artist["unique_tracks"],
                    artist["albums"],
                    hits_per_artist,
                    now,
                    artist["artist"]
                ))

                retained += 1

            else:
                connection.execute("""
                    INSERT INTO scheduler_artists (
                        artist,
                        unique_tracks,
                        album_count,
                        status,
                        hits_requested,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, 'pending', ?, ?, ?)
                """, (
                    artist["artist"],
                    artist["unique_tracks"],
                    artist["albums"],
                    hits_per_artist,
                    now,
                    now
                ))

                added += 1

        scheduler_set_setting(
            connection,
            "minimum_tracks",
            minimum_tracks
        )
        scheduler_set_setting(
            connection,
            "hits_per_artist",
            hits_per_artist
        )
        scheduler_set_setting(
            connection,
            "daily_limit",
            daily_limit
        )

        connection.commit()

        total = connection.execute("""
            SELECT COUNT(*)
            FROM scheduler_artists
        """).fetchone()[0]

    return {
        "success": True,
        "downloads_started": False,
        "added": added,
        "retained": retained,
        "total_queued_artists": total,
        "minimum_tracks": minimum_tracks,
        "hits_per_artist": hits_per_artist,
        "daily_limit": daily_limit,
        "estimated_storage_gb":
            preview["estimated_storage_gb"]
    }


@app.get("/api/scheduler/status")
def persistent_scheduler_status():
    initialise_scheduler_database()

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row

        totals = connection.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(
                    CASE WHEN status = 'pending'
                    THEN 1 ELSE 0 END
                ) AS pending,
                SUM(
                    CASE WHEN status = 'running'
                    THEN 1 ELSE 0 END
                ) AS running,
                SUM(
                    CASE WHEN status = 'completed'
                    THEN 1 ELSE 0 END
                ) AS completed,
                SUM(
                    CASE WHEN status = 'failed'
                    THEN 1 ELSE 0 END
                ) AS failed,
                COALESCE(SUM(downloaded), 0)
                    AS downloaded,
                COALESCE(SUM(already_exists), 0)
                    AS already_exists
            FROM scheduler_artists
        """).fetchone()

        settings_rows = connection.execute("""
            SELECT setting, value
            FROM scheduler_settings
        """).fetchall()

        artists = connection.execute("""
            SELECT
                artist,
                unique_tracks,
                album_count,
                status,
                hits_requested,
                downloaded,
                already_exists,
                failed,
                last_error
            FROM scheduler_artists
            ORDER BY
                CASE status
                    WHEN 'running' THEN 1
                    WHEN 'pending' THEN 2
                    WHEN 'failed' THEN 3
                    WHEN 'completed' THEN 4
                    ELSE 5
                END,
                artist COLLATE NOCASE
        """).fetchall()

    settings = {
        row["setting"]: row["value"]
        for row in settings_rows
    }

    return {
        "totals": dict(totals),
        "settings": settings,
        "artists": [
            dict(artist)
            for artist in artists
        ]
    }


scheduler_runtime = {
    "running": False,
    "stop_requested": False,
    "stage": "idle",
    "current_artist": "",
    "current_track": "",
    "downloaded_today": 0,
    "daily_limit": 50,
    "message": ""
}


def scheduler_get_setting(
    connection,
    name,
    default
):
    row = connection.execute("""
        SELECT value
        FROM scheduler_settings
        WHERE setting = ?
    """, (name,)).fetchone()

    return row[0] if row else default


def scheduler_count_today(connection):
    today = datetime.now(
        timezone.utc
    ).date().isoformat()

    row = connection.execute("""
        SELECT COUNT(*)
        FROM video_downloads
        WHERE status = 'completed'
          AND completed_at LIKE ?
    """, (today + "%",)).fetchone()

    return row[0] if row else 0


def run_persistent_scheduler():
    global scheduler_runtime

    scheduler_runtime.update({
        "running": True,
        "stop_requested": False,
        "stage": "starting",
        "current_artist": "",
        "current_track": "",
        "message": ""
    })

    initialise_scheduler_database()
    initialise_video_downloads()

    try:
        with sqlite3.connect(
            DATABASE_PATH
        ) as connection:
            connection.execute("""
                UPDATE scheduler_artists
                SET status = 'pending'
                WHERE status = 'running'
            """)
            connection.commit()

        while not scheduler_runtime[
            "stop_requested"
        ]:
            with sqlite3.connect(
                DATABASE_PATH
            ) as connection:
                connection.row_factory = sqlite3.Row

                daily_limit = int(
                    scheduler_get_setting(
                        connection,
                        "daily_limit",
                        50
                    )
                )

                downloaded_today = (
                    scheduler_count_today(connection)
                )

                scheduler_runtime[
                    "daily_limit"
                ] = daily_limit

                scheduler_runtime[
                    "downloaded_today"
                ] = downloaded_today

                if downloaded_today >= daily_limit:
                    scheduler_runtime[
                        "stage"
                    ] = "daily_limit"

                    scheduler_runtime[
                        "message"
                    ] = (
                        "Daily download limit reached"
                    )
                    break

                artist_row = connection.execute("""
                    SELECT
                        artist,
                        hits_requested
                    FROM scheduler_artists
                    WHERE status = 'pending'
                    ORDER BY artist COLLATE NOCASE
                    LIMIT 1
                """).fetchone()

                if not artist_row:
                    scheduler_runtime[
                        "stage"
                    ] = "completed"

                    scheduler_runtime[
                        "message"
                    ] = "All queued artists completed"
                    break

                artist_name = artist_row["artist"]
                hits_requested = artist_row[
                    "hits_requested"
                ]

                now = datetime.now(
                    timezone.utc
                ).isoformat()

                connection.execute("""
                    UPDATE scheduler_artists
                    SET
                        status = 'running',
                        last_error = NULL,
                        updated_at = ?
                    WHERE artist = ?
                """, (now, artist_name))

                connection.commit()

            scheduler_runtime[
                "stage"
            ] = "searching"

            scheduler_runtime[
                "current_artist"
            ] = artist_name

            scheduler_runtime[
                "current_track"
            ] = ""

            search = artist_hits(
                artist=artist_name,
                limit=hits_requested
            )

            if search.get("error"):
                raise RuntimeError(
                    search["error"]
                )

            hits = search.get("hits", [])

            downloaded_count = 0
            existing_count = 0
            failed_count = 0
            artist_interrupted = False

            scheduler_runtime[
                "stage"
            ] = "processing"

            for hit in hits:
                if scheduler_runtime[
                    "stop_requested"
                ]:
                    artist_interrupted = True
                    break

                with sqlite3.connect(
                    DATABASE_PATH
                ) as connection:
                    downloaded_today = (
                        scheduler_count_today(
                            connection
                        )
                    )

                    daily_limit = int(
                        scheduler_get_setting(
                            connection,
                            "daily_limit",
                            50
                        )
                    )

                if downloaded_today >= daily_limit:
                    scheduler_runtime[
                        "stage"
                    ] = "daily_limit"

                    scheduler_runtime[
                        "message"
                    ] = (
                        "Daily download limit reached"
                    )

                    artist_interrupted = True
                    break

                scheduler_runtime[
                    "current_track"
                ] = hit["track_title"]

                result = process_music_video(
                    ProductionRequest(
                        track_id=hit["track_id"],
                        video_id=hit["video_id"]
                    )
                )

                if result.get("success"):
                    if result.get(
                        "already_exists"
                    ):
                        existing_count += 1
                    else:
                        downloaded_count += 1
                        scheduler_increment_today()
                else:
                    failed_count += 1

                    scheduler_runtime[
                        "message"
                    ] = result.get(
                        "error",
                        "Video processing failed"
                    )

                with sqlite3.connect(
                    DATABASE_PATH
                ) as connection:
                    connection.execute("""
                        UPDATE scheduler_artists
                        SET
                            downloaded = downloaded + ?,
                            already_exists =
                                already_exists + ?,
                            failed = failed + ?,
                            updated_at = ?
                        WHERE artist = ?
                    """, (
                        1 if (
                            result.get("success")
                            and not result.get(
                                "already_exists"
                            )
                        ) else 0,
                        1 if result.get(
                            "already_exists"
                        ) else 0,
                        1 if not result.get(
                            "success"
                        ) else 0,
                        datetime.now(
                            timezone.utc
                        ).isoformat(),
                        artist_name
                    ))

                    connection.commit()

                if not result.get(
                    "already_exists"
                ):
                    import time
                    time.sleep(3)

            with sqlite3.connect(
                DATABASE_PATH
            ) as connection:
                if artist_interrupted:
                    new_status = "pending"
                elif failed_count and not (
                    downloaded_count
                    or existing_count
                ):
                    new_status = "failed"
                else:
                    new_status = "completed"

                connection.execute("""
                    UPDATE scheduler_artists
                    SET
                        status = ?,
                        last_error = ?,
                        updated_at = ?
                    WHERE artist = ?
                """, (
                    new_status,
                    (
                        scheduler_runtime["message"]
                        if failed_count else None
                    ),
                    datetime.now(
                        timezone.utc
                    ).isoformat(),
                    artist_name
                ))

                connection.commit()

            if artist_interrupted:
                break

        if scheduler_runtime["stop_requested"]:
            scheduler_runtime["stage"] = "stopped"
            scheduler_runtime["message"] = (
                "Stopped after current video"
            )

    except Exception as error:
        scheduler_runtime["stage"] = "failed"
        scheduler_runtime["message"] = str(error)

        current_artist = scheduler_runtime[
            "current_artist"
        ]

        if current_artist:
            with sqlite3.connect(
                DATABASE_PATH
            ) as connection:
                connection.execute("""
                    UPDATE scheduler_artists
                    SET
                        status = 'failed',
                        last_error = ?,
                        updated_at = ?
                    WHERE artist = ?
                """, (
                    str(error),
                    datetime.now(
                        timezone.utc
                    ).isoformat(),
                    current_artist
                ))
                connection.commit()

    finally:
        scheduler_runtime["running"] = False
        scheduler_runtime["current_track"] = ""


@app.post("/api/scheduler/start")
def start_persistent_scheduler():
    if scheduler_runtime["running"]:
        return {
            "success": False,
            "message": "Scheduler is already running"
        }

    threading.Thread(
        target=run_persistent_scheduler,
        daemon=True
    ).start()

    return {
        "success": True,
        "message": "Scheduler started"
    }


@app.post("/api/scheduler/stop")
def stop_persistent_scheduler():
    if not scheduler_runtime["running"]:
        return {
            "success": False,
            "message": "Scheduler is not running"
        }

    scheduler_runtime["stop_requested"] = True

    return {
        "success": True,
        "message": (
            "Stopping after the current video"
        )
    }


@app.get("/api/scheduler/runtime")
def get_scheduler_runtime():
    scheduler_runtime["downloaded_today"] = (
        scheduler_count_today()
    )
    return scheduler_runtime


@app.get("/scheduler", response_class=HTMLResponse)
def scheduler_page():
    return """
    <!doctype html>
    <html>
    <head>
        <title>All Artists Scheduler</title>
        <style>
            body {
                background: #101218;
                color: #f4f4f5;
                font-family: Arial, sans-serif;
                max-width: 1200px;
                margin: 30px auto;
                padding: 0 20px;
            }
            a { color: #a78bfa; }
            .panel {
                background: #1c2028;
                border: 1px solid #343b49;
                border-radius: 14px;
                padding: 22px;
                margin: 18px 0;
            }
            .stats {
                display: grid;
                grid-template-columns: repeat(5, 1fr);
                gap: 12px;
            }
            .stat {
                background: #272c36;
                border-radius: 10px;
                padding: 15px;
            }
            .number {
                color: #a78bfa;
                font-size: 27px;
                font-weight: bold;
            }
            button {
                color: white;
                border: 0;
                border-radius: 8px;
                padding: 12px 20px;
                margin-right: 8px;
                cursor: pointer;
            }
            button:disabled {
                opacity: .45;
                cursor: wait;
            }
            #start { background: #16a34a; }
            #stop { background: #dc2626; }
            .progress {
                background: #272c36;
                height: 22px;
                border-radius: 12px;
                overflow: hidden;
                margin: 18px 0;
            }
            #bar {
                background: #7c3aed;
                width: 0;
                height: 100%;
                transition: width .5s;
            }
            table {
                width: 100%;
                border-collapse: collapse;
            }
            th, td {
                padding: 10px;
                border-bottom: 1px solid #343b49;
                text-align: left;
            }
            th { color: #a78bfa; }
            .completed { color: #86efac; }
            .running { color: #facc15; }
            .failed { color: #fb7185; }
            .pending { color: #9ca3af; }
            #current {
                color: #c4b5fd;
                font-size: 18px;
            }
        </style>
    </head>
    <body>
        <nav>
            <a href="/">Scanner</a> ·
            <a href="/production">Production</a> ·
            <a href="/queue">Artist Queue</a>
        </nav>

        <h1>All Artists Scheduler</h1>

        <p>
            Top 10 for 86 eligible artists. Maximum 50 new
            videos per day. Existing files are skipped.
        </p>

        <div class="panel">
            <button id="start" onclick="startScheduler()">
                Start / Resume
            </button>

            <button
                id="stop"
                onclick="stopScheduler()"
                disabled
            >
                Stop After Current Video
            </button>

            <h2 id="stage">IDLE</h2>
            <div id="current"></div>
            <div id="message"></div>

            <div class="progress">
                <div id="bar"></div>
            </div>

            <div class="stats">
                <div class="stat">
                    <div class="number" id="total">0</div>
                    Artists
                </div>
                <div class="stat">
                    <div class="number" id="pending">0</div>
                    Waiting
                </div>
                <div class="stat">
                    <div class="number" id="completed">0</div>
                    Completed
                </div>
                <div class="stat">
                    <div class="number" id="downloaded">0</div>
                    Downloaded
                </div>
                <div class="stat">
                    <div class="number" id="today">0/50</div>
                    Today
                </div>
            </div>
        </div>

        <div class="panel">
            <h2>Artist Queue</h2>
            <table>
                <thead>
                    <tr>
                        <th>Artist</th>
                        <th>Status</th>
                        <th>Downloaded</th>
                        <th>Existing</th>
                        <th>Failed</th>
                    </tr>
                </thead>
                <tbody id="artists"></tbody>
            </table>
        </div>

        <script>
            async function startScheduler() {
                if (!confirm(
                    "Start the all-artists scheduler? " +
                    "It can download up to 50 new videos today."
                )) return;

                const response = await fetch(
                    "/api/scheduler/start",
                    {method: "POST"}
                );

                const result = await response.json();
                message.textContent = result.message;
                refresh();
            }

            async function stopScheduler() {
                const response = await fetch(
                    "/api/scheduler/stop",
                    {method: "POST"}
                );

                const result = await response.json();
                message.textContent = result.message;
            }

            async function refresh() {
                try {
                    const [statusResponse, runtimeResponse] =
                        await Promise.all([
                            fetch("/api/scheduler/status"),
                            fetch("/api/scheduler/runtime")
                        ]);

                    const status = await statusResponse.json();
                    const runtime = await runtimeResponse.json();
                    const totals = status.totals;

                    total.textContent = totals.total || 0;
                    pending.textContent = totals.pending || 0;
                    completed.textContent =
                        totals.completed || 0;
                    downloaded.textContent =
                        totals.downloaded || 0;
                    today.textContent =
                        `${runtime.downloaded_today}/` +
                        `${runtime.daily_limit}`;

                    stage.textContent =
                        runtime.stage.toUpperCase();

                    current.textContent =
                        runtime.current_artist
                        ? `${runtime.current_artist}` +
                          (
                            runtime.current_track
                            ? ` — ${runtime.current_track}`
                            : ""
                          )
                        : "";

                    message.textContent =
                        runtime.message || "";

                    start.disabled = runtime.running;
                    stop.disabled = !runtime.running;

                    const percentage = totals.total
                        ? Math.round(
                            (totals.completed || 0) /
                            totals.total * 100
                        )
                        : 0;

                    bar.style.width = `${percentage}%`;

                    artists.innerHTML = status.artists.map(
                        item => `
                        <tr>
                            <td>${escapeHtml(item.artist)}</td>
                            <td class="${item.status}">
                                ${item.status}
                            </td>
                            <td>${item.downloaded}</td>
                            <td>${item.already_exists}</td>
                            <td>${item.failed}</td>
                        </tr>
                    `).join("");

                } catch (error) {
                    message.textContent =
                        "Status error: " + error.message;
                }
            }

            function escapeHtml(value) {
                const node = document.createElement("div");
                node.textContent = value || "";
                return node.innerHTML;
            }

            refresh();
            setInterval(refresh, 2000);
        </script>
    </body>
    </html>
    """


def initialise_scheduler_daily():
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS scheduler_daily (
                download_date TEXT PRIMARY KEY,
                downloaded INTEGER NOT NULL DEFAULT 0
            )
        """)
        connection.commit()


def scheduler_count_today(connection=None):
    initialise_scheduler_daily()

    today = datetime.now(
        timezone.utc
    ).date().isoformat()

    with sqlite3.connect(DATABASE_PATH) as daily_connection:
        row = daily_connection.execute("""
            SELECT downloaded
            FROM scheduler_daily
            WHERE download_date = ?
        """, (today,)).fetchone()

    return row[0] if row else 0


def scheduler_increment_today():
    initialise_scheduler_daily()

    today = datetime.now(
        timezone.utc
    ).date().isoformat()

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("""
            INSERT INTO scheduler_daily (
                download_date,
                downloaded
            )
            VALUES (?, 1)
            ON CONFLICT(download_date) DO UPDATE SET
                downloaded = downloaded + 1
        """, (today,))
        connection.commit()


