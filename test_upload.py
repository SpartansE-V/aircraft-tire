#!/usr/bin/env python3
"""
Simple script to test S3 presigned URL upload endpoints.
"""
import argparse
import json
import sys
from pathlib import Path

import requests


PRESIGNER_URL = "https://g47l98hx5f.execute-api.ap-southeast-1.amazonaws.com/api/v1/uploads/presign"
DIRECT_UPLOAD_URL = "https://g47l98hx5f.execute-api.ap-southeast-1.amazonaws.com/api/v1/uploads/images"


def direct_upload(image_path: Path) -> dict:
    """Upload image directly via multipart/form-data (≤4MB)."""
    print(f"📤 Direct uploading {image_path.name}...")

    with open(image_path, "rb") as f:
        files = {"file": (image_path.name, f, "image/jpeg")}
        response = requests.post(DIRECT_UPLOAD_URL, files=files, timeout=30)

    response.raise_for_status()
    result = response.json()
    print(f"✅ Uploaded successfully!")
    print(f"   Key: {result['key']}")
    print(f"   ETag: {result.get('etag')}")
    return result


def presigned_upload(image_path: Path) -> dict:
    """Upload image via presigned URL (2-step: get URL, then PUT)."""
    print(f"📤 Presigned URL upload for {image_path.name}...")

    # Step 1: Request presigned URL
    print("   1. Requesting presigned URL...")
    payload = {
        "action": "put",
        "fileName": image_path.name,
        "contentType": "image/jpeg"
    }
    response = requests.post(PRESIGNER_URL, json=payload, timeout=10)
    response.raise_for_status()
    presign_result = response.json()

    upload_url = presign_result["uploadUrl"]
    key = presign_result["key"]
    print(f"   📋 Got presigned URL (expires in {presign_result['expiresIn']}s)")
    print(f"   🔑 Key: {key}")

    # Step 2: PUT file to S3 using presigned URL
    print("   2. Uploading to S3...")
    with open(image_path, "rb") as f:
        headers = {"Content-Type": "image/jpeg"}
        put_response = requests.put(upload_url, data=f, headers=headers, timeout=60)

    put_response.raise_for_status()
    etag = put_response.headers.get("ETag", "").strip('"')
    print(f"✅ Uploaded successfully!")
    print(f"   ETag: {etag}")

    return {"key": key, "etag": etag}


def main():
    parser = argparse.ArgumentParser(description="Test S3 upload endpoints")
    parser.add_argument("image", type=Path, help="Path to image file")
    parser.add_argument(
        "--method",
        choices=["direct", "presigned", "both"],
        default="presigned",
        help="Upload method (default: presigned)"
    )
    args = parser.parse_args()

    if not args.image.exists():
        print(f"❌ Error: File not found: {args.image}", file=sys.stderr)
        sys.exit(1)

    file_size = args.image.stat().st_size
    print(f"📁 File: {args.image.name} ({file_size:,} bytes)")
    print()

    try:
        if args.method in ("direct", "both"):
            if file_size > 4 * 1024 * 1024:
                print("⚠️  File too large for direct upload (>4MB), skipping...")
            else:
                result = direct_upload(args.image)
                print()

        if args.method in ("presigned", "both"):
            result = presigned_upload(args.image)
            print()

        print("🎉 All uploads completed!")

    except requests.HTTPError as e:
        print(f"❌ HTTP Error: {e}", file=sys.stderr)
        if e.response is not None:
            print(f"   Response: {e.response.text}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
