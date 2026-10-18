"""One declarative description per job stage: contracts, provider routing, processing and policy."""

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel

from ..config import Settings
from ..job_errors import LOCAL_PROVIDERS, JobErrorCode

# Failures of read-only local work that an explicit resume can safely repeat: processors reuse
# artifacts already committed for the same job, and no provider is billed.
TRANSIENT_LOCAL = frozenset(
    {
        JobErrorCode.DEADLINE_EXCEEDED,
        JobErrorCode.PROVIDER_TIMEOUT,
        JobErrorCode.PROVIDER_TRANSPORT,
        JobErrorCode.IO_ERROR,
        JobErrorCode.MEDIA_INVALID,
        JobErrorCode.PROCESS_FAILED,
    }
)


@dataclass(frozen=True)
class RetryPolicy:
    """Which failures a person may explicitly resume. Nothing here retries automatically.

    Paid stages without a known remote job are never resumable: an interrupted submission may
    already be billed, so a new explicit request (and estimate) is required instead.
    """

    retryable_errors: frozenset[str] = frozenset()
    # Resuming a remote job is safe only from phases that never resubmit or rebill.
    remote_resume_phases: frozenset[str] = frozenset()
    # Local, idempotent work may be resumed after a transient failure.
    local_resume: bool = False
    # Phase in which a remote submission is in flight; a restart there is ambiguous (maybe billed).
    submission_phase: str | None = None

    def retryable_after(self, job, code: str) -> bool:
        if job.remote_job_id and (self.retryable_errors or self.remote_resume_phases):
            return code in self.retryable_errors or job.phase in self.remote_resume_phases
        if self.remote_resume_phases:
            return False
        return (
            self.local_resume and job.provider in LOCAL_PROVIDERS and code in self.retryable_errors
        )

    def can_resume(self, job) -> bool:
        if job.status != "failed" or not job.retryable:
            return False
        if job.error_code == JobErrorCode.RESTORED_JOB_HOLD:
            return job.provider in LOCAL_PROVIDERS
        if job.remote_job_id:
            return True
        return self.local_resume and job.provider in LOCAL_PROVIDERS


LOCAL_RESUME = RetryPolicy(retryable_errors=TRANSIENT_LOCAL, local_resume=True)


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
