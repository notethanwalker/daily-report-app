from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

UPLOAD_ROOT = Path(os.getenv("STOOQ_UPLOAD_TEMP_DIR") or tempfile.gettempdir()) / "daily-report-stooq-uploads"
MAX_UPLOAD_BYTES = int(os.getenv("STOOQ_MANUAL_UPLOAD_MAX_BYTES", str(2 * 1024 * 1024 * 1024)))
DEFAULT_CHUNK_BYTES = int(os.getenv("STOOQ_UPLOAD_CHUNK_BYTES", str(8 * 1024 * 1024)))


def _dir(upload_id: str) -> Path:
    return UPLOAD_ROOT / upload_id


def _manifest_path(upload_id: str) -> Path:
    return _dir(upload_id) / "manifest.json"


def _archive_path(upload_id: str) -> Path:
    return _dir(upload_id) / "archive.zip"


def _load(upload_id: str) -> dict:
    path = _manifest_path(upload_id)
    if not path.exists():
        raise FileNotFoundError("Unknown Stooq upload session")
    return json.loads(path.read_text(encoding="utf-8"))


def _save(upload_id: str, manifest: dict) -> None:
    _manifest_path(upload_id).write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")


def create_upload(filename: str, total_bytes: int) -> dict:
    if total_bytes <= 0 or total_bytes > MAX_UPLOAD_BYTES:
        raise ValueError(f"Archive size must be between 1 and {MAX_UPLOAD_BYTES} bytes")
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    upload_id = uuid.uuid4().hex
    folder = _dir(upload_id)
    folder.mkdir(parents=True, exist_ok=False)
    archive = _archive_path(upload_id)
    with open(archive, "wb") as handle:
        handle.truncate(total_bytes)
    manifest = {
        "upload_id": upload_id,
        "filename": Path(filename or "d_us_txt.zip").name,
        "total_bytes": int(total_bytes),
        "chunk_bytes": DEFAULT_CHUNK_BYTES,
        "received": [],
        "status": "uploading",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save(upload_id, manifest)
    return manifest


def write_chunk(upload_id: str, offset: int, body: bytes) -> dict:
    manifest = _load(upload_id)
    if manifest.get("status") != "uploading":
        raise ValueError("Upload session is not accepting chunks")
    total = int(manifest["total_bytes"])
    if offset < 0 or not body or offset + len(body) > total:
        raise ValueError("Invalid Stooq archive chunk range")
    with open(_archive_path(upload_id), "r+b") as handle:
        handle.seek(offset)
        handle.write(body)
    received = list(manifest.get("received") or [])
    received.append([offset, offset + len(body)])
    received.sort()
    merged = []
    for start, end in received:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    manifest["received"] = merged
    manifest["received_bytes"] = sum(end - start for start, end in merged)
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save(upload_id, manifest)
    return manifest


def finalize_upload(upload_id: str) -> tuple[str, dict]:
    manifest = _load(upload_id)
    total = int(manifest["total_bytes"])
    received = manifest.get("received") or []
    if received != [[0, total]]:
        raise ValueError(f"Archive upload is incomplete: {manifest.get('received_bytes', 0)} of {total} bytes received")
    manifest["status"] = "queued_for_import"
    manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    _save(upload_id, manifest)
    return str(_archive_path(upload_id)), manifest


def mark_imported(upload_id: str, result: dict | None = None, error: str | None = None) -> None:
    try:
        manifest = _load(upload_id)
    except FileNotFoundError:
        return
    manifest["status"] = "failed" if error else "imported"
    manifest["import_result"] = result
    manifest["error"] = error
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    _save(upload_id, manifest)


def upload_status(upload_id: str) -> dict:
    return _load(upload_id)


def cleanup_upload(upload_id: str) -> None:
    folder = _dir(upload_id)
    if not folder.exists():
        return
    for path in folder.iterdir():
        try:
            path.unlink()
        except OSError:
            pass
    try:
        folder.rmdir()
    except OSError:
        pass
