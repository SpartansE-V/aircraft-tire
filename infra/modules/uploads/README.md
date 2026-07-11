# Image upload presigner

Terraform exposes `upload_presigner_url`, a public `POST /api/v1/uploads/presign`
endpoint. The Lambda accepts JSON and returns short-lived S3 URLs for the
private uploads bucket. It only accepts image MIME types and always generates
the object key under `uploads/<uuid>/`.

## Direct multipart API

`POST /api/v1/uploads/images`

For images up to 4 MiB, upload directly through the API with one field named
`file`:

```bash
curl -X POST "$IMAGE_UPLOAD_URL" \
  -F "aircraft_id=aircraft-uuid" \
  -F "tail_number=VN-A701" \
  -F "wheel_position=LEFT_MAIN_INBOARD" \
  -F "file=@tire-left.jpg;type=image/jpeg"
```

The endpoint validates the declared MIME type against the file signature and
returns `201` with the S3 `key`, `etag`, and `versionId`. Use the presigned flow
below for larger images.

## Small image (single PUT)

Create a URL:

```json
{
  "action": "put",
  "fileName": "tire-left.jpg",
  "contentType": "image/jpeg",
  "aircraftId": "aircraft-uuid",
  "tailNumber": "VN-A701",
  "wheelPosition": "LEFT_MAIN_INBOARD"
}
```

Upload the raw file bytes to `uploadUrl` using `PUT`. The request must include
the same `Content-Type` value used above.

## S3 multipart upload

1. Create the upload and one URL per part:

   ```json
   {
     "action": "createMultipart",
     "fileName": "tire-scan.tiff",
     "contentType": "image/tiff",
     "partCount": 3,
     "aircraftId": "aircraft-uuid",
     "tailNumber": "VN-A701",
     "wheelPosition": "LEFT_MAIN_INBOARD"
   }
   ```

2. Upload each raw part to its `uploadUrl` with `PUT` and record the `ETag`
   response header. Except for the final part, S3 requires every part to be at
   least 5 MiB.

3. Complete the upload with the returned `key`, `uploadId`, and ETags:

   ```json
   {
     "action": "completeMultipart",
     "key": "uploads/00000000-0000-0000-0000-000000000000/tire-scan.tiff",
     "uploadId": "the-upload-id",
     "parts": [
       {"partNumber": 1, "etag": "\"etag-1\""},
       {"partNumber": 2, "etag": "\"etag-2\""},
       {"partNumber": 3, "etag": "\"etag-3\""}
     ]
   }
   ```

To cancel, send `action: "abortMultipart"` with the same `key` and `uploadId`.
The bucket lifecycle also aborts incomplete multipart uploads after seven days.

The endpoint currently has no application authentication. CORS limits browser
origins but is not an authorization boundary; add an API Gateway authorizer
before exposing this outside the current trusted application environment.

## Image metadata

Every upload creates a record in the `aircraft-tire-upload-images` DynamoDB
table. `image_id` is the primary key. The `aircraft-created-at-index` GSI uses
`aircraft_id` as its partition key and `created_at` as its sort key, allowing
images to be queried per aircraft in chronological order.

The table uses on-demand billing, point-in-time recovery, encryption at rest,
and deletion protection. Disable deletion protection explicitly before an
intentional Terraform destroy.

Records contain `aircraft_id`, optional `tail_number` and `wheel_position`, S3
bucket/key, original filename, MIME type, size, ETag/version, upload status, and
UTC timestamps. Upload status moves through `PENDING`, `UPLOADED`, `FAILED`, or
`ABORTED`; S3 ObjectCreated events reconcile presigned uploads after the client
writes the object directly to S3.
