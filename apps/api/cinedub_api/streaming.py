"""Range-aware media responses without thread-pool file operations."""

import re
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import Response, StreamingResponse


def media_response(
    path: Path, media_type: str, request: Request, filename: str, download: bool = False
) -> Response:
    size = path.stat().st_size
    start, end = 0, size - 1
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'{"attachment" if download else "inline"}; filename="{filename}"',
    }
    status = 200
    value = request.headers.get("range")
    if value:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
        if not match or not any(match.groups()) or not size:
            raise HTTPException(
                416, "Unsupported byte range", headers={"Content-Range": f"bytes */{size}"}
            )
        first, last = match.groups()
        if not first:
            length = int(last)
            if length <= 0:
                raise HTTPException(
                    416, "Invalid suffix range", headers={"Content-Range": f"bytes */{size}"}
                )
            start = max(0, size - length)
        else:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
        if start >= size or start > end:
            raise HTTPException(
                416, "Range outside media", headers={"Content-Range": f"bytes */{size}"}
            )
        status = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    length = max(0, end - start + 1)
    headers["Content-Length"] = str(length)
    if request.method == "HEAD":
        return Response(status_code=status, headers=headers, media_type=media_type)

    async def chunks():
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining:
                chunk = handle.read(min(256 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(chunks(), status_code=status, headers=headers, media_type=media_type)
