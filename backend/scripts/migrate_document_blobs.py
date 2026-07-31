"""Move document blobs from local disk into the configured object store.

Needed once, when a deployment switches from local storage to object storage: the database
rows are backend-agnostic - ``storage_path`` means the same thing under either - but the bytes
themselves do not move on their own, so every document uploaded before the switch reads back
as "the stored file is missing".

**Verifies before it deletes, and only deletes when asked.** Each blob is uploaded, read back
out of the object store, and hashed; the local file is removed only if the digest matches the
one recorded on the row. A copy that has not been proven readable is not a copy.

Usage::

    uv run python scripts/migrate_document_blobs.py            # copy, keep local files
    uv run python scripts/migrate_document_blobs.py --purge    # copy, then delete verified
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

import app.db.registry  # noqa: F401  - registers every mapper
from app.core.config import settings
from app.db.session import SessionFactory
from app.modules.ocr.models import Document
from app.modules.ocr.storage import DocumentStore, document_store, sha256_of


async def main() -> int:
    purge = "--purge" in sys.argv

    if settings.document_storage != "object":
        print(
            "Object storage is not configured, so there is nowhere to move blobs to.\n"
            "Set MINIO_ENDPOINT, MINIO_ACCESS_KEY and MINIO_SECRET_KEY first.",
            file=sys.stderr,
        )
        return 2

    async with SessionFactory() as session:
        rows = (
            await session.execute(
                select(
                    Document.id, Document.original_filename, Document.storage_path, Document.sha256
                )
            )
        ).all()

    print(f"{len(rows)} document row(s), including soft-deleted")
    print(f"target: {settings.minio_endpoint}/{settings.minio_bucket}")
    print(f"source: {settings.upload_dir}")
    print("mode:  ", "copy then delete verified local files" if purge else "copy only")

    local = DocumentStore()
    remote = document_store()

    copied = missing = already = failed = 0

    for _document_id, name, path, digest in rows:
        # Soft-deleted rows are included deliberately: their blob is still referenced by
        # the row, and leaving it behind would strand it when the directory is wiped.
        if await remote.exists(path):
            already += 1
            continue

        source = Path(settings.upload_dir) / path
        if not source.exists():
            print(f"  MISSING LOCALLY  {name}  ({path})")
            missing += 1
            continue

        try:
            data = await local.read(path, verify=digest)
        except Exception as exc:
            print(f"  UNREADABLE       {name}: {exc}")
            failed += 1
            continue

        await remote.write(path, data)

        # Read it back out of the object store rather than trusting the write.
        verified = await remote.read(path, verify=digest)
        if sha256_of(verified) != digest:
            print(f"  VERIFY FAILED    {name} - leaving the local copy in place")
            failed += 1
            continue

        copied += 1
        if purge:
            source.unlink()
            print(f"  moved            {name}  ({len(data):,} bytes)")
        else:
            print(f"  copied           {name}  ({len(data):,} bytes)")

    print(
        f"\ncopied {copied}, already present {already}, missing locally {missing}, failed {failed}"
    )
    if copied and not purge:
        print("\nLocal files kept. Re-run with --purge to remove the verified ones.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
