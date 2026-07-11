import base64
import json
import os
import re
import uuid
from collections.abc import Mapping
from email import policy
from email.parser import BytesParser
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

UPLOAD_BUCKET = os.environ["UPLOAD_BUCKET"]
URL_EXPIRATION_SECS = int(os.environ.get("URL_EXPIRATION_SECS", "900"))
MAX_DIRECT_UPLOAD_BYTES = int(os.environ.get("MAX_DIRECT_UPLOAD_BYTES", str(4 * 1024 * 1024)))
MAX_MULTIPART_PARTS = 100
PRESIGN_PATH = "/api/v1/uploads/presign"
IMAGE_UPLOAD_PATH = "/api/v1/uploads/images"
ALLOWED_CONTENT_TYPES = {
    "image/avif",
    "image/gif",
    "image/heic",
    "image/heif",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "image/webp",
}
KEY_PATTERN = re.compile(r"^uploads/[0-9a-f-]{36}/[A-Za-z0-9._-]{1,120}$")
SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")

s3 = boto3.client("s3")


class RequestError(ValueError):
    pass


def _response(status_code: int, payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(payload, separators=(",", ":")),
    }


def _parse_body(event: Mapping[str, Any]) -> dict[str, Any]:
    body = event.get("body")
    if not isinstance(body, str) or not body:
        raise RequestError("Request body must be a JSON object.")

    if event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(body, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise RequestError("Request body is not valid base64-encoded UTF-8.") from exc

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RequestError("Request body must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise RequestError("Request body must be a JSON object.")
    return payload


def _body_bytes(event: Mapping[str, Any]) -> bytes:
    body = event.get("body")
    if not isinstance(body, str) or not body:
        raise RequestError("Request body is required.")
    if event.get("isBase64Encoded"):
        try:
            return base64.b64decode(body, validate=True)
        except ValueError as exc:
            raise RequestError("Request body is not valid base64.") from exc
    return body.encode("utf-8")


def _header(event: Mapping[str, Any], name: str) -> str | None:
    headers = event.get("headers")
    if not isinstance(headers, Mapping):
        return None
    expected = name.lower()
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == expected and isinstance(value, str):
            return value
    return None


def _image_type(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if content.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    if len(content) >= 12 and content[4:8] == b"ftyp":
        brand = content[8:12]
        if brand in {b"avif", b"avis"}:
            return "image/avif"
        if brand in {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}:
            return "image/heic"
    return None


def _multipart_image(event: Mapping[str, Any]) -> tuple[str, str, bytes]:
    content_type = _header(event, "content-type")
    if not content_type or not content_type.lower().startswith("multipart/form-data;"):
        raise RequestError("Content-Type must be multipart/form-data with a boundary.")

    body = _body_bytes(event)
    if len(body) > MAX_DIRECT_UPLOAD_BYTES + 64 * 1024:
        raise RequestError(f"Uploaded image cannot exceed {MAX_DIRECT_UPLOAD_BYTES} bytes.")

    envelope = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
    message = BytesParser(policy=policy.default).parsebytes(envelope)
    files = [
        part
        for part in message.iter_parts()
        if part.get_param("name", header="content-disposition") == "file"
    ]
    if len(files) != 1:
        raise RequestError("Multipart body must contain exactly one file field named 'file'.")

    part = files[0]
    filename = part.get_filename()
    content = part.get_payload(decode=True)
    if not isinstance(filename, str) or not filename.strip():
        raise RequestError("Uploaded file must have a filename.")
    if not isinstance(content, bytes) or not content:
        raise RequestError("Uploaded image cannot be empty.")
    if len(content) > MAX_DIRECT_UPLOAD_BYTES:
        raise RequestError(f"Uploaded image cannot exceed {MAX_DIRECT_UPLOAD_BYTES} bytes.")

    declared_type = part.get_content_type().lower()
    detected_type = _image_type(content)
    compatible_types = {
        "image/heic": {"image/heic", "image/heif"},
    }
    if detected_type is None or declared_type not in compatible_types.get(
        detected_type, {detected_type}
    ):
        raise RequestError("File content does not match its supported image Content-Type.")
    return filename, declared_type, content


def _upload_image(event: Mapping[str, Any]) -> dict[str, Any]:
    filename, content_type, content = _multipart_image(event)
    key = _new_key({"fileName": filename})
    uploaded = s3.put_object(
        Bucket=UPLOAD_BUCKET,
        Key=key,
        Body=content,
        ContentType=content_type,
    )
    return {
        "key": key,
        "etag": uploaded.get("ETag"),
        "versionId": uploaded.get("VersionId"),
    }


def _content_type(payload: Mapping[str, Any]) -> str:
    value = payload.get("contentType")
    if not isinstance(value, str) or value not in ALLOWED_CONTENT_TYPES:
        raise RequestError("contentType must be a supported image MIME type.")
    return value


def _new_key(payload: Mapping[str, Any]) -> str:
    filename = payload.get("fileName")
    if not isinstance(filename, str) or not filename.strip():
        raise RequestError("fileName is required.")

    basename = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    safe_name = SAFE_FILENAME_PATTERN.sub("-", basename).strip(".-")
    if not safe_name:
        safe_name = "image"
    safe_name = safe_name[:120]
    return f"uploads/{uuid.uuid4()}/{safe_name}"


def _existing_upload(payload: Mapping[str, Any]) -> tuple[str, str]:
    key = payload.get("key")
    upload_id = payload.get("uploadId")
    if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
        raise RequestError("key is invalid.")
    if not isinstance(upload_id, str) or not upload_id or len(upload_id) > 1024:
        raise RequestError("uploadId is invalid.")
    return key, upload_id


def _create_put(payload: Mapping[str, Any]) -> dict[str, Any]:
    content_type = _content_type(payload)
    key = _new_key(payload)
    url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": UPLOAD_BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=URL_EXPIRATION_SECS,
        HttpMethod="PUT",
    )
    return {"action": "put", "key": key, "uploadUrl": url, "expiresIn": URL_EXPIRATION_SECS}


def _create_multipart(payload: Mapping[str, Any]) -> dict[str, Any]:
    content_type = _content_type(payload)
    part_count = payload.get("partCount")
    if isinstance(part_count, bool) or not isinstance(part_count, int):
        raise RequestError("partCount must be an integer.")
    if not 1 <= part_count <= MAX_MULTIPART_PARTS:
        raise RequestError(f"partCount must be between 1 and {MAX_MULTIPART_PARTS}.")

    key = _new_key(payload)
    created = s3.create_multipart_upload(
        Bucket=UPLOAD_BUCKET,
        Key=key,
        ContentType=content_type,
    )
    upload_id = created["UploadId"]
    part_urls = [
        {
            "partNumber": part_number,
            "uploadUrl": s3.generate_presigned_url(
                "upload_part",
                Params={
                    "Bucket": UPLOAD_BUCKET,
                    "Key": key,
                    "UploadId": upload_id,
                    "PartNumber": part_number,
                },
                ExpiresIn=URL_EXPIRATION_SECS,
                HttpMethod="PUT",
            ),
        }
        for part_number in range(1, part_count + 1)
    ]
    return {
        "action": "createMultipart",
        "key": key,
        "uploadId": upload_id,
        "parts": part_urls,
        "expiresIn": URL_EXPIRATION_SECS,
    }


def _complete_multipart(payload: Mapping[str, Any]) -> dict[str, Any]:
    key, upload_id = _existing_upload(payload)
    raw_parts = payload.get("parts")
    if not isinstance(raw_parts, list) or not raw_parts:
        raise RequestError("parts must be a non-empty array.")
    if len(raw_parts) > MAX_MULTIPART_PARTS:
        raise RequestError(f"parts cannot contain more than {MAX_MULTIPART_PARTS} entries.")

    parts: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in raw_parts:
        if not isinstance(item, dict):
            raise RequestError("Each part must be an object.")
        part_number = item.get("partNumber")
        etag = item.get("etag")
        if (
            isinstance(part_number, bool)
            or not isinstance(part_number, int)
            or not 1 <= part_number <= MAX_MULTIPART_PARTS
            or part_number in seen
        ):
            raise RequestError("Each partNumber must be unique and between 1 and 100.")
        if not isinstance(etag, str) or not etag.strip() or len(etag) > 128:
            raise RequestError("Each part must include a valid etag.")
        seen.add(part_number)
        parts.append({"PartNumber": part_number, "ETag": etag.strip()})

    parts.sort(key=lambda item: item["PartNumber"])
    completed = s3.complete_multipart_upload(
        Bucket=UPLOAD_BUCKET,
        Key=key,
        UploadId=upload_id,
        MultipartUpload={"Parts": parts},
    )
    return {
        "action": "completeMultipart",
        "key": key,
        "etag": completed.get("ETag"),
        "versionId": completed.get("VersionId"),
    }


def _abort_multipart(payload: Mapping[str, Any]) -> dict[str, Any]:
    key, upload_id = _existing_upload(payload)
    s3.abort_multipart_upload(Bucket=UPLOAD_BUCKET, Key=key, UploadId=upload_id)
    return {"action": "abortMultipart", "key": key}


def lambda_handler(event: Mapping[str, Any], _context: Any) -> dict[str, Any]:
    try:
        path = event.get("rawPath")
        if path == IMAGE_UPLOAD_PATH:
            return _response(201, _upload_image(event))
        if path != PRESIGN_PATH:
            return _response(404, {"error": "Route not found."})

        payload = _parse_body(event)
        action = payload.get("action", "put")
        handlers = {
            "put": _create_put,
            "createMultipart": _create_multipart,
            "completeMultipart": _complete_multipart,
            "abortMultipart": _abort_multipart,
        }
        handler = handlers.get(action)
        if handler is None:
            raise RequestError(
                "action must be put, createMultipart, completeMultipart, or abortMultipart."
            )
        return _response(200, handler(payload))
    except RequestError as exc:
        return _response(400, {"error": str(exc)})
    except (BotoCoreError, ClientError):
        return _response(502, {"error": "S3 could not process the upload request."})
