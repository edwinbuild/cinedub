"""Stable job error codes. The UI maps each code to an action; messages stay provider-safe."""

from enum import StrEnum

import httpx

from .media import MediaError
from .providers.retry import safe_error


class JobErrorCode(StrEnum):
    INPUT_INVALID = "input_invalid"
    OUTPUT_INVALID = "output_invalid"
    STALE_INPUT = "stale_input"
    INVALID_REQUEST = "invalid_request"
    BUDGET_EXCEEDED = "budget_exceeded"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_TRANSPORT = "provider_transport"
    PROVIDER_REJECTED = "provider_rejected"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    MEDIA_INVALID = "media_invalid"
    IO_ERROR = "io_error"
    PROCESS_FAILED = "process_failed"
    STORAGE_FULL = "storage_full"
    CANCELLED = "cancelled"
    UNCERTAIN_SUBMISSION = "uncertain_submission"
    UNCERTAIN_REGISTRATION = "uncertain_registration"
    RESTORED_JOB_HOLD = "restored_job_hold"
    INTERNAL = "internal"


class InvalidJobInput(ValueError):
    """Stored inputs no longer match the stage contract; resubmit explicitly."""


class InvalidJobOutput(ValueError):
    """A processor result failed its stage contract and was not recorded."""


class StaleInput(ValueError):
    """Frozen inputs no longer match saved project state; schedule a new request."""


class BudgetExhausted(ValueError):
    """A job tried to charge beyond its reserved estimate."""


LOCAL_PROVIDERS = {"local", "fake"}


def classify(exc: Exception, job) -> tuple[JobErrorCode, str]:
    """Map a processor failure to a stable code and a message safe to show and store."""
    if job.stage == "register_voice" and job.checkpoint_json.get("pending_registration"):
        return (
            JobErrorCode.UNCERTAIN_REGISTRATION,
            "Voice upload outcome is unknown. Inspect provider voices/usage before an explicit "
            "retry.",
        )
    message = safe_error(exc)
    match exc:
        case InvalidJobInput():
            return JobErrorCode.INPUT_INVALID, message
        case InvalidJobOutput():
            return JobErrorCode.OUTPUT_INVALID, message
        case StaleInput():
            return JobErrorCode.STALE_INPUT, message
        case BudgetExhausted():
            return JobErrorCode.BUDGET_EXCEEDED, message
        case TimeoutError() if job.provider in LOCAL_PROVIDERS:
            return (
                JobErrorCode.DEADLINE_EXCEEDED,
                "Local processing deadline exceeded; the process stopped. Retry explicitly.",
            )
        case TimeoutError() | httpx.TimeoutException():
            return JobErrorCode.PROVIDER_TIMEOUT, message
        case ConnectionError() | httpx.TransportError():
            return JobErrorCode.PROVIDER_TRANSPORT, message
        case httpx.HTTPStatusError():
            return JobErrorCode.PROVIDER_REJECTED, message
        case MediaError():
            return JobErrorCode.MEDIA_INVALID, message
        case OSError():
            return JobErrorCode.IO_ERROR, message
        case ValueError() | PermissionError():
            return JobErrorCode.INVALID_REQUEST, message
        case RuntimeError():
            return JobErrorCode.PROCESS_FAILED, message
    if getattr(exc, "status_code", None):
        return JobErrorCode.PROVIDER_REJECTED, message
    return JobErrorCode.INTERNAL, message
