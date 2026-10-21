"""Idempotent POSTs: a retried request with the same key and body replays the first response.

The same key with a different body is a client error (409). Entries expire after 24 hours.
Callers hold the write lock, so check-then-store cannot race another request.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import IdempotencyKey

HEADER = "Idempotency-Key"
TTL = timedelta(hours=24)


def request_hash(*parts) -> str:
    return hashlib.sha256(
        json.dumps(parts, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


class Idempotency:
    def __init__(self, session: Session, request: Request, digest: str = ""):
        self.session = session
        self.key = request.headers.get(HEADER)
        if self.key is not None and not 1 <= len(self.key) <= 128:
            raise HTTPException(422, "Idempotency-Key must be 1–128 characters")
        self.route = f"{request.method} {request.url.path}"
        self.digest = digest

    def stored(self) -> IdempotencyKey | None:
        """The earlier response for this key and route, after expiring old entries."""
        if not self.key:
            return None
        self.session.execute(
            delete(IdempotencyKey).where(IdempotencyKey.created_at < datetime.now(UTC) - TTL)
        )
        return self.session.scalar(
            select(IdempotencyKey).where(
                IdempotencyKey.key == self.key, IdempotencyKey.route == self.route
            )
        )

    def respond(self, stored: IdempotencyKey) -> JSONResponse:
        if stored.request_hash != self.digest:
            raise HTTPException(409, "This Idempotency-Key was already used with another request")
        return JSONResponse(status_code=stored.status_code, content=stored.response_json)

    def replay(self) -> JSONResponse | None:
        stored = self.stored()
        return self.respond(stored) if stored else None

    def remember(self, status_code: int, body: dict) -> None:
        if self.key:
            self.session.add(
                IdempotencyKey(
                    key=self.key,
                    route=self.route,
                    request_hash=self.digest,
                    status_code=status_code,
                    response_json=body,
                )
            )
