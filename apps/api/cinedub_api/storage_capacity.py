"""Recognize real storage-capacity failures without inspecting SQL or provider text."""

import errno
import sqlite3

from sqlalchemy.exc import DBAPIError

STORAGE_MESSAGE = (
    "Storage capacity exhausted. Free space or resolve the quota for database, media and "
    "temporary storage, then restart CineDub. Saved work is retained; check job history "
    "and provider usage before explicitly retrying any paid operation."
)


class StorageCapacityError(RuntimeError):
    pass


def is_storage_capacity_error(error):
    if isinstance(error, StorageCapacityError):
        return True
    original = error.orig if isinstance(error, DBAPIError) else error
    if isinstance(original, OSError) and original.errno in {errno.ENOSPC, errno.EDQUOT}:
        return True
    code = getattr(original, "sqlite_errorcode", None)
    return (
        isinstance(original, sqlite3.Error)
        and isinstance(code, int)
        and code & 255 == sqlite3.SQLITE_FULL
    )
