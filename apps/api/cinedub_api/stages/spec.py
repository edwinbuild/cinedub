"""One declarative description per job stage: contracts, provider routing, processing and policy."""

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel

from ..config import Settings


@dataclass(frozen=True)
class RetryPolicy:
    """Which failures a person may explicitly resume. Nothing here retries automatically."""

    retryable_errors: frozenset[str] = frozenset()
    # Resuming a remote job is safe only from phases that never resubmit or rebill.
    remote_resume_phases: frozenset[str] = frozenset()
    max_attempts: int = 3


@dataclass(frozen=True)
class StageSpec:
    stage: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    process: Callable
    default_provider: Callable[[Settings], str]
    # Ordered preparation steps; each mutates the shared preparation context.
    prepare: tuple[Callable, ...] = ()
    capability: str | None = None
    # Created only by internal workflows (for example packaging an accepted mix).
    internal: bool = False
    review_gate: str | None = None
    retry: RetryPolicy = field(default_factory=RetryPolicy)
