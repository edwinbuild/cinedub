"""Bounded retries that never expose provider headers or signed URLs."""

import time
from collections.abc import Callable

import httpx


def safe_error(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
    if status:
        return f"Provider returned HTTP {status}; check credentials, credit, or request settings"
    if isinstance(exc, (httpx.TransportError, TimeoutError)):
        return "Provider connection timed out or failed; remote billing outcome may be unknown"
    if isinstance(exc, (ValueError, PermissionError, InterruptedError, RuntimeError)):
        # Application-raised messages only. SDK errors are never stringified.
        return (
            str(exc)[:400]
            if not type(exc).__module__.startswith("sarvamai")
            else "Provider request failed"
        )
    return "Processing failed; inspect the source and retry explicitly"


def retry_safe[T](
    operation: Callable[[], T],
    check_cancel: Callable[[], None],
    before_attempt: Callable[[], None] | None = None,
) -> T:
    for attempt in range(3):
        check_cancel()
        if before_attempt:
            before_attempt()
        try:
            return operation()
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            headers = getattr(exc, "headers", None) or {}
            if isinstance(exc, httpx.HTTPStatusError):
                status, headers = exc.response.status_code, exc.response.headers
            # Transport ambiguity is not automatically retried for a billed operation.
            transient = status == 429 or (status is not None and 500 <= status < 600)
            if before_attempt is None and isinstance(exc, httpx.TransportError):
                transient = True
            if not transient or attempt == 2:
                raise
            try:
                delay = min(60, max(2**attempt, float(headers.get("retry-after", 0))))
            except (TypeError, ValueError):
                delay = 2**attempt
            # Check cancellation while backing off.
            until = time.monotonic() + delay
            while time.monotonic() < until:
                check_cancel()
                time.sleep(min(0.5, max(0, until - time.monotonic())))
    raise AssertionError("Unreachable")
