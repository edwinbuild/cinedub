"""Server-sent project events with cheap change detection.

Each poll compares small change tokens (counts and latest timestamps) instead of serialising
every job. Only what changed is sent: job and pipeline updates as full records, timeline and
artifact changes as tokens telling the client to refetch the project. A reconnect (with or
without `Last-Event-ID`) starts with a fresh snapshot of current state, never a replay.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable

from sqlalchemy import func, select

from .database import SessionLocal
from .models import Artifact, Job, Pipeline, Project, Segment, Speaker
from .schemas import JobRead, PipelineRead

HEARTBEAT_SECONDS = 15


def _stamp(value) -> str | None:
    return value.isoformat() if value else None


def _token(session, model, project_id, *extra) -> str:
    count, latest = session.execute(
        select(
            func.count(model.id),
            func.max(model.updated_at if hasattr(model, "updated_at") else model.created_at),
        ).where(model.project_id == project_id, *extra)
    ).one()
    return f"{count}:{_stamp(latest)}"


def snapshot_tokens(session, project: Project) -> dict:
    return {
        "project": project.status,
        "timeline": "|".join(
            [
                str(project.active_revision_id),
                _token(session, Segment, project.id),
                _token(session, Speaker, project.id),
            ]
        ),
        "artifact": _token(session, Artifact, project.id),
    }


def _since(session, model, project_id, after):
    query = select(model).where(model.project_id == project_id)
    if after is not None:
        query = query.where(model.updated_at > after)
    return session.scalars(query.order_by(model.updated_at)).all()


async def project_event_stream(
    project_id: str,
    is_disconnected: Callable[[], Awaitable[bool]],
    *,
    poll_seconds: float = 1.0,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
) -> AsyncIterator[str]:
    sequence = 0
    tokens: dict = {}
    seen = {"job": None, "pipeline": None}
    idle = 0.0

    def message(kind: str, data: dict) -> str:
        nonlocal sequence
        sequence += 1
        payload = json.dumps({"type": kind, **data}, separators=(",", ":"), default=str)
        return f"id: {sequence}\nevent: {kind}\ndata: {payload}\n\n"

    while not await is_disconnected():
        out = []
        with SessionLocal() as session:
            project = session.get(Project, project_id)
            if not project:
                yield message("error", {"detail": "Project not found"})
                return
            for kind, model, schema in (
                ("job", Job, JobRead),
                ("pipeline", Pipeline, PipelineRead),
            ):
                records = _since(session, model, project_id, seen[kind])
                for record in records:
                    out.append(
                        message(kind, {kind: schema.model_validate(record).model_dump(mode="json")})
                    )
                if records:
                    seen[kind] = records[-1].updated_at
            current = snapshot_tokens(session, project)
            if current["project"] != tokens.get("project"):
                out.append(message("project", {"status": current["project"]}))
            if current["timeline"] != tokens.get("timeline"):
                out.append(
                    message(
                        "timeline",
                        {"revision_id": project.active_revision_id, "token": current["timeline"]},
                    )
                )
            if current["artifact"] != tokens.get("artifact"):
                out.append(message("artifact", {"token": current["artifact"]}))
            tokens = current
        for item in out:
            yield item
        idle = 0.0 if out else idle + poll_seconds
        if idle >= heartbeat_seconds:
            idle = 0.0
            yield ": keepalive\n\n"
        await asyncio.sleep(poll_seconds)
