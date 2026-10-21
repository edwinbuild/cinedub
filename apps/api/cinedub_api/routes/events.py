"""Server-sent project events (typed `ProjectEvent` payloads; see events.py)."""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..events import project_event_stream

router = APIRouter()


@router.get("/projects/{project_id}/events")
async def project_events(project_id: str, request: Request) -> StreamingResponse:
    return StreamingResponse(
        project_event_stream(project_id, request.is_disconnected),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
