import base64
import json
import os
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
from typing import Any
from urllib.parse import unquote_plus

import boto3
from botocore.exceptions import BotoCoreError, ClientError

UPLOAD_BUCKET = os.environ["UPLOAD_BUCKET"]
IMAGE_TABLE = os.environ["IMAGE_TABLE"]
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
dynamodb = boto3.client("dynamodb")


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


def _text_field(
    payload: Mapping[str, Any], key: str, *, required: bool = False, max_length: int = 128
) -> str | None:
    value = payload.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RequestError(f"{key} is required." if required else f"{key} must be text.")
    value = value.strip()
    if len(value) > max_length:
        raise RequestError(f"{key} cannot exceed {max_length} characters.")
    return value


def _aircraft_metadata(payload: Mapping[str, Any]) -> dict[str, str]:
    aircraft_id = _text_field(payload, "aircraftId", required=True)
    assert aircraft_id is not None
    metadata = {"aircraft_id": aircraft_id}
    tail_number = _text_field(payload, "tailNumber", max_length=32)
    wheel_position = _text_field(payload, "wheelPosition", max_length=64)
    if tail_number:
        metadata["tail_number"] = tail_number
    if wheel_position:
        metadata["wheel_position"] = wheel_position
    return metadata


def _multipart_image(event: Mapping[str, Any]) -> tuple[str, str, bytes, dict[str, str]]:
    content_type = _header(event, "content-type")
    if not content_type or not content_type.lower().startswith("multipart/form-data;"):
        raise RequestError("Content-Type must be multipart/form-data with a boundary.")

    body = _body_bytes(event)
    if len(body) > MAX_DIRECT_UPLOAD_BYTES + 64 * 1024:
        raise RequestError(f"Uploaded image cannot exceed {MAX_DIRECT_UPLOAD_BYTES} bytes.")

    envelope = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
    message = BytesParser(policy=policy.default).parsebytes(envelope)
    parts = list(message.iter_parts())
    files = [
        part for part in parts if part.get_param("name", header="content-disposition") == "file"
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

    form_fields: dict[str, str] = {}
    field_aliases = {
        "aircraft_id": "aircraftId",
        "tail_number": "tailNumber",
        "wheel_position": "wheelPosition",
    }
    for form_name, json_name in field_aliases.items():
        matching = [
            candidate
            for candidate in parts
            if candidate.get_param("name", header="content-disposition") == form_name
        ]
        if len(matching) > 1:
            raise RequestError(f"Multipart field '{form_name}' cannot be repeated.")
        if matching:
            value = matching[0].get_content()
            if isinstance(value, str):
                form_fields[json_name] = value
    return filename, declared_type, content, _aircraft_metadata(form_fields)


def _image_id(key: str) -> str:
    return key.split("/", 2)[1]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _create_image_record(
    *,
    key: str,
    filename: str,
    content_type: str,
    metadata: Mapping[str, str],
    size_bytes: int | None = None,
    upload_id: str | None = None,
) -> None:
    timestamp = _now()
    item = {
        "image_id": {"S": _image_id(key)},
        "aircraft_id": {"S": metadata["aircraft_id"]},
        "s3_bucket": {"S": UPLOAD_BUCKET},
        "s3_key": {"S": key},
        "original_filename": {"S": filename},
        "content_type": {"S": content_type},
        "upload_status": {"S": "PENDING"},
        "created_at": {"S": timestamp},
        "updated_at": {"S": timestamp},
    }
    for name in ("tail_number", "wheel_position"):
        if value := metadata.get(name):
            item[name] = {"S": value}
    if size_bytes is not None:
        item["size_bytes"] = {"N": str(size_bytes)}
    if upload_id:
        item["multipart_upload_id"] = {"S": upload_id}

    dynamodb.put_item(
        TableName=IMAGE_TABLE,
        Item=item,
        ConditionExpression="attribute_not_exists(image_id)",
    )


def _update_image_status(
    image_id: str,
    status: str,
    *,
    etag: str | None = None,
    version_id: str | None = None,
    size_bytes: int | None = None,
) -> None:
    names = {"#status": "upload_status"}
    values = {
        ":status": {"S": status},
        ":updated": {"S": _now()},
    }
    assignments = ["#status = :status", "updated_at = :updated"]
    for name, value, data_type in (
        ("etag", etag, "S"),
        ("version_id", version_id, "S"),
        ("size_bytes", size_bytes, "N"),
    ):
        if value is not None:
            placeholder = f":{name}"
            assignments.append(f"{name} = {placeholder}")
            values[placeholder] = {data_type: str(value)}

    dynamodb.update_item(
        TableName=IMAGE_TABLE,
        Key={"image_id": {"S": image_id}},
        UpdateExpression=f"SET {', '.join(assignments)}",
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ConditionExpression="attribute_exists(image_id)",
    )


def _upload_image(event: Mapping[str, Any]) -> dict[str, Any]:
    filename, content_type, content, metadata = _multipart_image(event)
    key = _new_key({"fileName": filename})
    image_id = _image_id(key)
    _create_image_record(
        key=key,
        filename=filename,
        content_type=content_type,
        metadata=metadata,
        size_bytes=len(content),
    )
    try:
        uploaded = s3.put_object(
            Bucket=UPLOAD_BUCKET,
            Key=key,
            Body=content,
            ContentType=content_type,
        )
    except (BotoCoreError, ClientError):
        _update_image_status(image_id, "FAILED")
        raise
    _update_image_status(
        image_id,
        "UPLOADED",
        etag=uploaded.get("ETag"),
        version_id=uploaded.get("VersionId"),
        size_bytes=len(content),
    )
    return {
        "imageId": image_id,
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
    metadata = _aircraft_metadata(payload)
    key = _new_key(payload)
    url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": UPLOAD_BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=URL_EXPIRATION_SECS,
        HttpMethod="PUT",
    )
    _create_image_record(
        key=key,
        filename=str(payload["fileName"]),
        content_type=content_type,
        metadata=metadata,
    )
    return {
        "action": "put",
        "imageId": _image_id(key),
        "key": key,
        "uploadUrl": url,
        "expiresIn": URL_EXPIRATION_SECS,
    }


def _create_multipart(payload: Mapping[str, Any]) -> dict[str, Any]:
    content_type = _content_type(payload)
    metadata = _aircraft_metadata(payload)
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
    try:
        _create_image_record(
            key=key,
            filename=str(payload["fileName"]),
            content_type=content_type,
            metadata=metadata,
            upload_id=upload_id,
        )
    except (BotoCoreError, ClientError):
        s3.abort_multipart_upload(Bucket=UPLOAD_BUCKET, Key=key, UploadId=upload_id)
        raise
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
        "imageId": _image_id(key),
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
    _update_image_status(
        _image_id(key),
        "UPLOADED",
        etag=completed.get("ETag"),
        version_id=completed.get("VersionId"),
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
    _update_image_status(_image_id(key), "ABORTED")
    return {"action": "abortMultipart", "key": key}


def _handle_s3_event(event: Mapping[str, Any]) -> dict[str, int]:
    processed = 0
    records = event.get("Records")
    if not isinstance(records, list):
        return {"processed": processed}
    for record in records:
        try:
            s3_record = record["s3"]
            key = unquote_plus(s3_record["object"]["key"])
            if not KEY_PATTERN.fullmatch(key):
                continue
            _update_image_status(
                _image_id(key),
                "UPLOADED",
                etag=s3_record["object"].get("eTag"),
                version_id=s3_record["object"].get("versionId"),
                size_bytes=s3_record["object"].get("size"),
            )
            processed += 1
        except (KeyError, TypeError):
            continue
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
    return {"processed": processed}


def lambda_handler(event: Mapping[str, Any], _context: Any) -> dict[str, Any]:
    try:
        if "Records" in event:
            return _handle_s3_event(event)

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
        return _response(502, {"error": "Upload storage could not process the request."})
