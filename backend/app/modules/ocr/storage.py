"""Blob storage for uploaded documents.

**Content-addressed.** A blob lives at a path derived from the SHA-256 of its own
bytes, and nowhere else. Three things follow for free:

* The filename is never attacker-controlled. Joining a user-supplied name onto a
  directory is how ``../../../etc/authorized_keys`` becomes a write target, and no
  amount of sanitising is as safe as not doing it.
* Identical uploads cannot occupy two blobs.
* The address is a checksum, so silent disk corruption is detectable on read.

**Writes are atomic.** The bytes go to a temporary file that is then renamed into
place. ``rename`` within a filesystem is atomic, so a crash or a full disk mid-write
leaves either nothing or a complete blob — never a truncated file sitting at an
address that asserts what its contents hash to.

**File I/O runs in a worker thread.** ``open().write()`` blocks, and a 15 MB write to
a slow disk would stall the event loop for every concurrent request.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Final

import anyio.to_thread

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.modules.ocr.engines import DocumentFormat, DocumentTooLargeError

log = get_logger(__name__)

#: Read size when streaming an upload. 64 KiB is a good balance: large enough that
#: syscall overhead disappears, small enough that the limit check below rejects an
#: oversized body long before it is all in memory.
CHUNK_SIZE: Final = 64 * 1024


class StorageError(AppError):
    """The blob could not be written or read.

    A 500, not a 4xx: the client did nothing wrong, and a full or unwritable disk is
    an operator problem that should page someone rather than look like a bad request.
    """

    code = "storage_error"
    message = "The document could not be stored."


class BlobCorruptedError(StorageError):
    """A blob's bytes no longer hash to its address."""

    code = "blob_corrupted"
    message = "The stored document failed its integrity check."


def sha256_of(data: bytes) -> str:
    """Lowercase hex SHA-256."""
    return hashlib.sha256(data).hexdigest()


def relative_path_for(organization_id: object, digest: str, fmt: DocumentFormat) -> str:
    """The storage path for a blob, relative to the upload directory.

    Sharded on the first two hex characters. A single directory holding every blob
    is fine at a hundred documents and pathological at a hundred thousand — some
    filesystems degrade to linear scans, and ``ls`` becomes unusable for the operator
    who has to look. Two characters give 256 buckets, which is the right order of
    magnitude for a self-hosted install.

    Organization-first so a tenant's documents can be exported, audited, or removed
    with one directory operation.
    """
    return f"{organization_id}/{digest[:2]}/{digest}.{fmt.extension}"


def _absolute(relative: str) -> Path:
    """Resolve a relative blob path, refusing anything that escapes the root.

    Defence in depth. Paths here are built from a hex digest and a UUID, so none of
    them *can* contain ``..`` today — but this function is the only place that turns
    a stored string into a filesystem path, and a stored string is exactly what a
    future bug or a tampered row would poison.
    """
    root = settings.upload_dir.resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise StorageError(f"Refusing a storage path outside the upload root: {relative!r}")
    return candidate


class DocumentStore:
    """Reads and writes document blobs.

    A class rather than module functions so a test or a future S3 backend can be
    substituted at the one place that constructs it.
    """

    def _write_sync(self, relative: str, data: bytes) -> None:
        target = _absolute(relative)
        target.parent.mkdir(parents=True, exist_ok=True)

        # Already stored: content-addressed, so identical bytes are already there.
        # Rewriting would be pure risk for no gain.
        if target.exists() and target.stat().st_size == len(data):
            return

        try:
            # Same directory as the target, so the rename stays within one
            # filesystem — `os.replace` across devices is not atomic and raises.
            handle, temporary = tempfile.mkstemp(dir=target.parent, suffix=".part")
            try:
                with os.fdopen(handle, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    # Force the bytes to disk before the rename publishes the name.
                    # Without this, a power loss can leave a correctly-named, empty
                    # file — worse than a missing one, because it looks valid.
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            except BaseException:
                Path(temporary).unlink(missing_ok=True)
                raise
        except OSError as exc:
            log.error("blob write failed", extra={"path": relative, "error": str(exc)})
            raise StorageError from exc

    async def write(self, relative: str, data: bytes) -> None:
        """Store bytes at ``relative``, atomically."""
        await anyio.to_thread.run_sync(self._write_sync, relative, data)

    def _read_sync(self, relative: str, *, verify: str | None) -> bytes:
        target = _absolute(relative)
        try:
            data = target.read_bytes()
        except FileNotFoundError as exc:
            raise StorageError(
                "The stored file is missing. It may have been removed from disk.",
                code="blob_missing",
                status_code=410,
            ) from exc
        except OSError as exc:
            raise StorageError from exc

        if verify is not None and sha256_of(data) != verify:
            log.error("blob integrity check failed", extra={"path": relative})
            raise BlobCorruptedError

        return data

    async def read(self, relative: str, *, verify: str | None = None) -> bytes:
        """Read a blob, optionally checking it against its expected digest.

        Verification is opt-in rather than automatic: it costs a full hash pass, which
        is worth paying when the bytes are about to be shown to a user as evidence
        for a ledger entry, and not worth paying on every thumbnail request.
        """
        return await anyio.to_thread.run_sync(lambda: self._read_sync(relative, verify=verify))

    async def exists(self, relative: str) -> bool:
        return await anyio.to_thread.run_sync(lambda: _absolute(relative).exists())

    async def delete(self, relative: str) -> None:
        """Remove a blob.

        Only for a hard purge. Soft-deleting a :class:`~app.modules.ocr.models.Document`
        deliberately leaves its blob alone — a document that turned into a posted bill
        is the evidence for a ledger entry, and destroying it because someone tidied
        the review queue would leave the books unsupportable.
        """

        def _unlink() -> None:
            _absolute(relative).unlink(missing_ok=True)

        await anyio.to_thread.run_sync(_unlink)


async def read_within_limit(stream: object, *, limit: int | None = None) -> bytes:
    """Read an upload, aborting as soon as it exceeds the limit.

    **Chunked, not ``await file.read()``.** Reading the whole body first and checking
    its length afterwards means a 2 GB upload is a 2 GB allocation before the check
    runs — the size limit becomes a way to *report* the memory exhaustion it was
    supposed to prevent. Stopping at the first chunk that crosses the line caps the
    damage at one chunk.
    """
    ceiling = limit if limit is not None else settings.max_upload_bytes
    read = getattr(stream, "read", None)
    if read is None:  # pragma: no cover — guarded by the router's typing
        raise StorageError("Upload stream is not readable")

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await read(CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > ceiling:
            raise DocumentTooLargeError(
                f"That file is larger than the {ceiling // (1024 * 1024)} MB limit.",
                details={"max_bytes": ceiling},
            )
        chunks.append(chunk)

    return b"".join(chunks)
