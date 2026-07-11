import base64
import importlib.util
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ["UPLOAD_BUCKET"] = "test-uploads"
fake_s3 = MagicMock()
fake_boto3 = types.ModuleType("boto3")
fake_boto3.client = MagicMock(return_value=fake_s3)
fake_botocore = types.ModuleType("botocore")
fake_botocore_exceptions = types.ModuleType("botocore.exceptions")
fake_botocore_exceptions.BotoCoreError = type("BotoCoreError", (Exception,), {})
fake_botocore_exceptions.ClientError = type("ClientError", (Exception,), {})
sys.modules.setdefault("boto3", fake_boto3)
sys.modules.setdefault("botocore", fake_botocore)
sys.modules.setdefault("botocore.exceptions", fake_botocore_exceptions)

MODULE_PATH = Path(__file__).with_name("upload_presigner.py")
SPEC = importlib.util.spec_from_file_location("upload_presigner", MODULE_PATH)
assert SPEC and SPEC.loader
upload_presigner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(upload_presigner)


def invoke(payload):
    return upload_presigner.lambda_handler(
        {"rawPath": "/api/v1/uploads/presign", "body": json.dumps(payload)}, None
    )


def invoke_upload(content, content_type="image/png", filename="scan.png"):
    boundary = "test-boundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    return upload_presigner.lambda_handler(
        {
            "rawPath": "/api/v1/uploads/images",
            "headers": {"content-type": f"multipart/form-data; boundary={boundary}"},
            "isBase64Encoded": True,
            "body": base64.b64encode(body).decode(),
        },
        None,
    )


class UploadPresignerTests(unittest.TestCase):
    def setUp(self):
        fake_s3.reset_mock()
        fake_s3.generate_presigned_url.return_value = "https://signed.example/upload"

    @patch.object(
        upload_presigner.uuid,
        "uuid4",
        return_value="12345678-1234-1234-1234-123456789abc",
    )
    def test_put_returns_server_generated_key_and_signed_url(self, _uuid):
        response = invoke(
            {"action": "put", "fileName": "../left tire.jpg", "contentType": "image/jpeg"}
        )

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(
            body["key"], "uploads/12345678-1234-1234-1234-123456789abc/left-tire.jpg"
        )
        fake_s3.generate_presigned_url.assert_called_once()

    def test_rejects_non_image_content_type(self):
        response = invoke({"fileName": "payload.html", "contentType": "text/html"})

        self.assertEqual(response["statusCode"], 400)
        fake_s3.generate_presigned_url.assert_not_called()

    def test_create_multipart_returns_one_url_per_part(self):
        fake_s3.create_multipart_upload.return_value = {"UploadId": "upload-1"}

        response = invoke(
            {
                "action": "createMultipart",
                "fileName": "scan.png",
                "contentType": "image/png",
                "partCount": 3,
            }
        )

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["uploadId"], "upload-1")
        self.assertEqual([part["partNumber"] for part in body["parts"]], [1, 2, 3])
        self.assertEqual(fake_s3.generate_presigned_url.call_count, 3)

    def test_complete_sorts_parts_before_calling_s3(self):
        fake_s3.complete_multipart_upload.return_value = {"ETag": '"complete-etag"'}
        key = "uploads/12345678-1234-1234-1234-123456789abc/scan.png"

        response = invoke(
            {
                "action": "completeMultipart",
                "key": key,
                "uploadId": "upload-1",
                "parts": [
                    {"partNumber": 2, "etag": '"etag-2"'},
                    {"partNumber": 1, "etag": '"etag-1"'},
                ],
            }
        )

        self.assertEqual(response["statusCode"], 200)
        parts = fake_s3.complete_multipart_upload.call_args.kwargs["MultipartUpload"]["Parts"]
        self.assertEqual([part["PartNumber"] for part in parts], [1, 2])

    def test_rejects_duplicate_part_numbers(self):
        key = "uploads/12345678-1234-1234-1234-123456789abc/scan.png"
        response = invoke(
            {
                "action": "completeMultipart",
                "key": key,
                "uploadId": "upload-1",
                "parts": [
                    {"partNumber": 1, "etag": '"etag-1"'},
                    {"partNumber": 1, "etag": '"etag-1-again"'},
                ],
            }
        )

        self.assertEqual(response["statusCode"], 400)
        fake_s3.complete_multipart_upload.assert_not_called()

    def test_direct_upload_writes_valid_image_to_s3(self):
        fake_s3.put_object.return_value = {"ETag": '"etag"', "VersionId": "version-1"}

        response = invoke_upload(b"\x89PNG\r\n\x1a\nimage-content")

        self.assertEqual(response["statusCode"], 201)
        body = json.loads(response["body"])
        self.assertTrue(body["key"].endswith("/scan.png"))
        self.assertEqual(fake_s3.put_object.call_args.kwargs["ContentType"], "image/png")
        self.assertEqual(
            fake_s3.put_object.call_args.kwargs["Body"],
            b"\x89PNG\r\n\x1a\nimage-content",
        )

    def test_direct_upload_rejects_mime_mismatch(self):
        response = invoke_upload(b"\x89PNG\r\n\x1a\nimage-content", content_type="image/jpeg")

        self.assertEqual(response["statusCode"], 400)
        fake_s3.put_object.assert_not_called()


if __name__ == "__main__":
    unittest.main()
