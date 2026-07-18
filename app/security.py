from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


def hash_password(password: str, iterations: int = 600_000) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.b64decode(salt), int(rounds)
        )
        return hmac.compare_digest(digest, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


class RateLimiter:
    def __init__(self, limit: int, window: int):
        self.limit, self.window = limit, window
        self.attempts: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        entries = self.attempts[key]
        while entries and entries[0] < now - self.window:
            entries.popleft()
        if len(entries) >= self.limit:
            raise HTTPException(429, "Too many attempts; try again later")
        entries.append(now)


def require_auth(request: Request) -> None:
    if not request.session.get("authenticated"):
        raise HTTPException(401, "Authentication required")


def require_csrf(request: Request) -> None:
    require_auth(request)
    supplied = request.headers.get("X-CSRF-Token", "")
    expected = request.session.get("csrf", "")
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(403, "Invalid CSRF token")


def new_csrf() -> str:
    return secrets.token_urlsafe(32)
