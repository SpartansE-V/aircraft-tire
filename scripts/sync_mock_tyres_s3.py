#!/usr/bin/env python3
"""Upload mock-tyre PNGs via the uploads API and write an S3 key manifest.

Uses the direct multipart endpoint for files ≤4 MiB (all release PNGs qualify).
JSON metadata stays local — the API only accepts image MIME types.

Example:
  python scripts/sync_mock_tyres_s3.py
  python scripts/sync_mock_tyres_s3.py --force
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_DIR = REPO_ROOT / "assets" / "mock-tyres" / "release"
MANIFEST_PATHS = (
    RELEASE_DIR / "s3-manifest.json",
    REPO_ROOT / "app" / "tire_rul" / "config" / "mock_tyres_s3_manifest.json",
)

DEFAULT_PRESIGNER_URL = (
    "https://g47l98hx5f.execute-api.ap-southeast-1.amazonaws.com/api/v1/uploads/presign"
)
DEFAULT_DIRECT_URL = (
    "https://g47l98hx5f.execute-api.ap-southeast-1.amazonaws.com/api/v1/uploads/images"
)
DEFAULT_BUCKET = "aircraft-tire-uploads-442147575477"
MAX_DIRECT_BYTES = 4 * 1024 * 1024

UPLOAD_NAMES = frozenset(
    {
        "circle.png",
        "flatten-left.png",
        "flatten-right.png",
        "frame-0.png",
        "frame-120.png",
        "frame-240.png",
    }
)


def _content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed and guessed.startswith("image/"):
        return guessed
    return "image/png"


def _rel_key(path: Path) -> str:
    return path.relative_to(RELEASE_DIR).as_posix()


def _iter_upload_files() -> list[Path]:
    files: list[Path] = []
    root_circle = RELEASE_DIR / "circle.png"
    if root_circle.is_file():
        files.append(root_circle)
    for group_dir in sorted(p for p in RELEASE_DIR.iterdir() if p.is_dir()):
        for name in sorted(UPLOAD_NAMES):
            path = group_dir / name
            if path.is_file():
                files.append(path)
    return files


def _json_request(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None) -> dict:
    req = Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    with urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _put_bytes(url: str, body: bytes, content_type: str) -> str | None:
    req = Request(
        url,
        data=body,
        headers={"Content-Type": content_type},
        method="PUT",
    )
    with urlopen(req, timeout=180) as resp:
        etag = resp.headers.get("ETag", "").strip('"')
        return etag or None


def direct_upload(url: str, path: Path, *, aircraft_id: str) -> dict:
    content_type = _content_type(path)
    body = path.read_bytes()
    boundary = f"----aircraftTire{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    def add_field(name: str, value: str) -> None:
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        chunks.append(f"{value}\r\n".encode())

    add_field("aircraftId", aircraft_id)
    chunks.append(f"--{boundary}\r\n".encode())
    chunks.append(
        (
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
    )
    chunks.append(body)
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    payload = b"".join(chunks)

    req = Request(
        url,
        data=payload,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def presigned_upload(presign_url: str, path: Path, *, aircraft_id: str) -> dict:
    content_type = _content_type(path)
    payload = json.dumps(
        {
            "action": "put",
            "fileName": path.name,
            "contentType": content_type,
            "aircraftId": aircraft_id,
        }
    ).encode()
    result = _json_request(
        presign_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    etag = _put_bytes(result["uploadUrl"], path.read_bytes(), content_type)
    return {
        "key": result["key"],
        "etag": etag,
        "imageId": result.get("imageId"),
    }


def load_manifest(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifests(payload: dict) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    for dest in MANIFEST_PATHS:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        print(f"Wrote {dest.relative_to(REPO_ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct-url", default=DEFAULT_DIRECT_URL)
    parser.add_argument("--presign-url", default=DEFAULT_PRESIGNER_URL)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--aircraft-id", default="mock-tyres-release")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-upload even when the relative path is already in the manifest",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files that would be uploaded without calling the API",
    )
    args = parser.parse_args()

    if not RELEASE_DIR.is_dir():
        print(f"Missing release dir: {RELEASE_DIR}", file=sys.stderr)
        return 1

    existing = load_manifest(MANIFEST_PATHS[0]) or load_manifest(MANIFEST_PATHS[1])
    objects: dict[str, dict] = dict(existing.get("objects") or {})
    files = _iter_upload_files()
    print(f"Found {len(files)} PNG(s) under {RELEASE_DIR.relative_to(REPO_ROOT)}")

    if args.dry_run:
        for path in files:
            rel = _rel_key(path)
            status = "skip" if (rel in objects and not args.force) else "upload"
            print(f"  [{status}] {rel} ({path.stat().st_size:,} bytes)")
        return 0

    uploaded = 0
    skipped = 0
    errors = 0

    for path in files:
        rel = _rel_key(path)
        if rel in objects and not args.force:
            print(f"skip  {rel} → {objects[rel]['key']}")
            skipped += 1
            continue

        size = path.stat().st_size
        print(f"upload {rel} ({size:,} bytes)…", flush=True)
        try:
            if size <= MAX_DIRECT_BYTES:
                result = direct_upload(args.direct_url, path, aircraft_id=args.aircraft_id)
            else:
                result = presigned_upload(
                    args.presign_url, path, aircraft_id=args.aircraft_id
                )
            objects[rel] = {
                "key": result["key"],
                "etag": result.get("etag"),
                "imageId": result.get("imageId"),
                "bytes": size,
            }
            uploaded += 1
            print(f"  → {result['key']}")
            time.sleep(0.15)
        except HTTPError as exc:
            errors += 1
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            print(f"  ERROR HTTP {exc.code}: {body}", file=sys.stderr)
        except URLError as exc:
            errors += 1
            print(f"  ERROR {exc}", file=sys.stderr)

    if not objects:
        print("No objects uploaded; not writing an empty manifest.", file=sys.stderr)
        return 1

    payload = {
        "bucket": args.bucket,
        "source": "assets/mock-tyres/release",
        "uploadedVia": args.direct_url,
        "objects": dict(sorted(objects.items())),
    }
    write_manifests(payload)
    print(f"Done: uploaded={uploaded} skipped={skipped} errors={errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
