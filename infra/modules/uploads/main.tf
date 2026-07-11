resource "aws_s3_bucket" "uploads" {
  bucket = var.bucket_name

  tags = var.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_public_access_block" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"
    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_expiration_days
    }
  }

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"
    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_cors_configuration" "uploads" {
  count  = length(var.cors_allowed_origins) > 0 ? 1 : 0
  bucket = aws_s3_bucket.uploads.id

  cors_rule {
    allowed_methods = ["PUT", "POST", "GET"]
    allowed_origins = var.cors_allowed_origins
    allowed_headers = ["*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

resource "aws_dynamodb_table" "images" {
  name                        = "${var.project_name}-upload-images"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "image_id"
  deletion_protection_enabled = true

  attribute {
    name = "image_id"
    type = "S"
  }

  attribute {
    name = "aircraft_id"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "aircraft-created-at-index"
    hash_key        = "aircraft_id"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = var.tags
}

data "archive_file" "upload_presigner" {
  type        = "zip"
  source_file = "${path.module}/lambda/upload_presigner.py"
  output_path = "${path.module}/upload_presigner.zip"
}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "upload_presigner" {
  name               = "${var.project_name}-upload-presigner-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "upload_presigner_logs" {
  role       = aws_iam_role.upload_presigner.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "upload_presigner_s3" {
  statement {
    sid    = "WriteUploadObjects"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:PutObject",
    ]
    resources = ["${aws_s3_bucket.uploads.arn}/uploads/*"]
  }

  statement {
    sid    = "WriteImageMetadata"
    effect = "Allow"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
    ]
    resources = [aws_dynamodb_table.images.arn]
  }
}

resource "aws_iam_role_policy" "upload_presigner_s3" {
  name   = "${var.project_name}-upload-presigner-s3"
  role   = aws_iam_role.upload_presigner.id
  policy = data.aws_iam_policy_document.upload_presigner_s3.json
}

resource "aws_cloudwatch_log_group" "upload_presigner" {
  name              = "/aws/lambda/${var.project_name}-upload-presigner"
  retention_in_days = 14
  tags              = var.tags
}

resource "aws_lambda_function" "upload_presigner" {
  function_name = "${var.project_name}-upload-presigner"
  description   = "Creates presigned URLs and uploads small multipart images to S3."
  role          = aws_iam_role.upload_presigner.arn
  runtime       = "python3.12"
  handler       = "upload_presigner.lambda_handler"

  filename         = data.archive_file.upload_presigner.output_path
  source_code_hash = data.archive_file.upload_presigner.output_base64sha256

  memory_size = 128
  timeout     = 10
  # reserved_concurrent_executions removed - account quota too low

  environment {
    variables = {
      IMAGE_TABLE             = aws_dynamodb_table.images.name
      MAX_DIRECT_UPLOAD_BYTES = tostring(var.direct_upload_max_bytes)
      UPLOAD_BUCKET           = aws_s3_bucket.uploads.bucket
      URL_EXPIRATION_SECS     = tostring(var.presigned_url_expiration_secs)
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.upload_presigner,
    aws_iam_role_policy.upload_presigner_s3,
    aws_iam_role_policy_attachment.upload_presigner_logs,
  ]

  tags = var.tags
}

resource "aws_apigatewayv2_api" "upload_presigner" {
  name          = "${var.project_name}-upload-presigner"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = var.cors_allowed_origins
    allow_methods = ["POST"]
    allow_headers = ["content-type"]
    max_age       = 300
  }

  tags = var.tags
}

resource "aws_apigatewayv2_integration" "upload_presigner" {
  api_id                 = aws_apigatewayv2_api.upload_presigner.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.upload_presigner.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
  timeout_milliseconds   = 10000
}

resource "aws_apigatewayv2_route" "upload_presigner" {
  api_id    = aws_apigatewayv2_api.upload_presigner.id
  route_key = "POST /api/v1/uploads/presign"
  target    = "integrations/${aws_apigatewayv2_integration.upload_presigner.id}"
}

resource "aws_apigatewayv2_route" "image_upload" {
  api_id    = aws_apigatewayv2_api.upload_presigner.id
  route_key = "POST /api/v1/uploads/images"
  target    = "integrations/${aws_apigatewayv2_integration.upload_presigner.id}"
}

resource "aws_apigatewayv2_stage" "upload_presigner" {
  api_id      = aws_apigatewayv2_api.upload_presigner.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 10
    throttling_rate_limit  = 5
  }

  tags = var.tags
}

resource "aws_lambda_permission" "upload_presigner_api" {
  statement_id  = "AllowUploadPresignerApi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.upload_presigner.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.upload_presigner.execution_arn}/*/*"
}

resource "aws_lambda_permission" "upload_events" {
  statement_id  = "AllowUploadBucketEvents"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.upload_presigner.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.uploads.arn
}

resource "aws_s3_bucket_notification" "upload_events" {
  bucket = aws_s3_bucket.uploads.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.upload_presigner.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "uploads/"
  }

  depends_on = [aws_lambda_permission.upload_events]
}
