output "bucket_name" {
  value = aws_s3_bucket.uploads.bucket
}

output "bucket_arn" {
  value = aws_s3_bucket.uploads.arn
}

output "presigner_url" {
  value = "${aws_apigatewayv2_api.upload_presigner.api_endpoint}/api/v1/uploads/presign"
}

output "presigner_function_name" {
  value = aws_lambda_function.upload_presigner.function_name
}

output "image_upload_url" {
  value = "${aws_apigatewayv2_api.upload_presigner.api_endpoint}/api/v1/uploads/images"
}
