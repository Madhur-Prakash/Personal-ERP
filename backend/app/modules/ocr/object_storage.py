"""S3-compatible object storage for uploaded documents.

Same interface as :class:`~app.modules.ocr.storage.DocumentStore`, so nothing above it knows
which one it is talking to - the choice is made once, in
:func:`app.modules.ocr.storage.document_store`.

**S3-compatible rather than tied to one vendor.** The same code addresses MinIO running
beside the app in development, MinIO on the operator's own machine, or real S3 - which is the
point for a product whose premise is that you host it yourself. Nothing here depends on a
provider-specific feature.

**Objects are private, and the bytes come back exactly as they went in.** No transformation
pipeline, no re-encoding, no format parsing: a blob is addressed by the SHA-256 of its own
bytes and verified against that on read, so anything that rewrote a single byte would turn
every read into a corruption error. Object storage is the right shape for that; a media CDN
is not, which was worth learning the hard way.

**The client is synchronous, so every call runs in a worker thread.** A 15 MB upload on the
event loop stalls every concurrent request.

A note on durability: the development compose file runs MinIO **without a volume**, so
uploaded documents live only as long as the container. That is deliberate for a throwaway dev
stack and completely wrong anywhere else - a real deployment must mount storage, or the first
`docker compose down` takes the books' supporting evidence with it.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Final

import anyio.to_thread
from minio import Minio
from minio.error import S3Error

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.ocr.storage import BlobCorruptedError, StorageError, sha256_of

if TYPE_CHECKING:
    from collections.abc import Callable

log = get_logger(__name__)

#: S3 error codes that mean "the object is not there", as opposed to a real fault.
MISSING_CODES: Final[frozenset[str]] = frozenset({"NoSuchKey", "NoSuchObject", "NotFound"})


class ObjectDocumentStore:
    """Reads and writes document blobs in an S3-compatible bucket."""

    def __init__(self) -> None:
        self._client: Minio | None = None
        self._bucket_ready = False

    # -----------------------------------------------------------------------
    # Client
    # -----------------------------------------------------------------------
    def _connect(self) -> Minio:
        """The client, built once per store instance.

        Built lazily rather than in ``__init__`` so constructing the store - which happens
        on every request through the service - costs nothing until a blob is actually
        touched.
        """
        if self._client is None:
            self._client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key.get_secret_value(),
                secure=settings.minio_secure,
            )
        return self._client

    def _ensure_bucket(self, client: Minio) -> None:
        """Create the bucket if this deployment has not got one yet.

        MinIO starts empty, so a fresh stack has no bucket and the first upload would fail
        on something the operator has no reason to have done by hand. Checked once per store
        instance: the call is cheap, but not free, and it cannot change mid-request.

        The bucket is left with default (private) access. Making it public would expose
        every invoice to anyone who guessed a URL.
        """
        if self._bucket_ready:
            return
        try:
            if not client.bucket_exists(settings.minio_bucket):
                client.make_bucket(settings.minio_bucket)
                log.info("created the document bucket", extra={"bucket": settings.minio_bucket})
        except S3Error as exc:
            log.error(
                "could not reach the object store",
                extra={"bucket": settings.minio_bucket, "error": str(exc)},
            )
            raise StorageError from exc
        self._bucket_ready = True

    async def _in_thread[T](self, work: Callable[[Minio], T]) -> T:
        """Run one client call off the event loop, with the bucket guaranteed to exist."""

        def run() -> T:
            client = self._connect()
            self._ensure_bucket(client)
            return work(client)

        return await anyio.to_thread.run_sync(run)

    # -----------------------------------------------------------------------
    # Operations
    # -----------------------------------------------------------------------
    async def write(self, relative: str, data: bytes) -> None:
        """Store bytes under ``relative``.

        Content-addressed, so an object already at this key holds these exact bytes and
        re-uploading would be pure cost. Checked first for that reason, not for safety -
        overwriting would be harmless, just wasteful.
        """

        def work(client: Minio) -> None:
            try:
                client.stat_object(settings.minio_bucket, relative)
                return
            except S3Error as exc:
                if exc.code not in MISSING_CODES:
                    log.error(
                        "object store lookup failed before write",
                        extra={"key": relative, "code": exc.code},
                    )
                    raise StorageError from exc

            try:
                client.put_object(
                    settings.minio_bucket,
                    relative,
                    io.BytesIO(data),
                    length=len(data),
                    content_type=_content_type(relative),
                )
            except S3Error as exc:
                log.error("object store write failed", extra={"key": relative, "code": exc.code})
                raise StorageError from exc

        await self._in_thread(work)

    async def read(self, relative: str, *, verify: str | None = None) -> bytes:
        """Fetch a blob, optionally checking it against its expected digest.

        Verification matters more here than on a local disk, not less: the bytes have
        crossed a network and been held by another process, so "are these the bytes we
        stored" stops being a question only about disk corruption.
        """

        def work(client: Minio) -> bytes:
            response = None
            try:
                response = client.get_object(settings.minio_bucket, relative)
                return bytes(response.read())
            except S3Error as exc:
                if exc.code in MISSING_CODES:
                    raise StorageError(
                        "The stored file is missing. It may have been removed from storage.",
                        code="blob_missing",
                        status_code=410,
                    ) from exc
                log.error("object store read failed", extra={"key": relative, "code": exc.code})
                raise StorageError from exc
            finally:
                # Both required by the SDK: the response holds a pooled connection that is
                # not returned until it is released, and leaking those exhausts the pool
                # after a few hundred reads.
                if response is not None:
                    response.close()
                    response.release_conn()

        data = await self._in_thread(work)

        if verify is not None and sha256_of(data) != verify:
            log.error("blob integrity check failed", extra={"key": relative})
            raise BlobCorruptedError

        return data

    async def exists(self, relative: str) -> bool:
        def work(client: Minio) -> bool:
            try:
                client.stat_object(settings.minio_bucket, relative)
            except S3Error as exc:
                if exc.code in MISSING_CODES:
                    return False
                log.error("object store lookup failed", extra={"key": relative, "code": exc.code})
                raise StorageError from exc
            return True

        return await self._in_thread(work)

    async def delete(self, relative: str) -> None:
        """Remove a blob.

        A delete of something already absent is success: the goal is that it is gone.
        """

        def work(client: Minio) -> None:
            try:
                client.remove_object(settings.minio_bucket, relative)
            except S3Error as exc:
                if exc.code in MISSING_CODES:
                    return
                log.error("object store delete failed", extra={"key": relative, "code": exc.code})
                raise StorageError from exc

        await self._in_thread(work)


def _content_type(relative: str) -> str:
    """The MIME type to record on the object, from the key's extension.

    Stored so anything browsing the bucket - the MinIO console, a sync tool - sees a PDF as
    a PDF. It is metadata only: the application always trusts the type it sniffed from the
    bytes at upload, which is recorded on the document row.
    """
    _, _, extension = relative.rpartition(".")
    return {
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "tif": "image/tiff",
        "tiff": "image/tiff",
        "webp": "image/webp",
    }.get(extension.lower(), "application/octet-stream")


__all__ = ["ObjectDocumentStore"]
