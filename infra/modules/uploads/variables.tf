variable "project_name" {
  type = string
}

variable "cors_allowed_origins" {
  description = "Origins allowed to PUT/POST images directly to the bucket (e.g. browser multipart uploads)."
  type        = list(string)
  default     = []
}

variable "noncurrent_version_expiration_days" {
  description = "Days to keep noncurrent object versions before expiring them."
  type        = number
  default     = 30
}

variable "presigned_url_expiration_secs" {
  description = "Lifetime of presigned S3 PUT and UploadPart URLs."
  type        = number
  default     = 900

  validation {
    condition     = var.presigned_url_expiration_secs >= 60 && var.presigned_url_expiration_secs <= 3600
    error_message = "presigned_url_expiration_secs must be between 60 and 3600 seconds."
  }
}

variable "direct_upload_max_bytes" {
  description = "Maximum image size accepted by the multipart API before clients must use presigned upload."
  type        = number
  default     = 4194304

  validation {
    condition     = var.direct_upload_max_bytes >= 1 && var.direct_upload_max_bytes <= 4194304
    error_message = "direct_upload_max_bytes must be between 1 byte and 4 MiB."
  }
}

variable "tags" {
  type    = map(string)
  default = {}
}
