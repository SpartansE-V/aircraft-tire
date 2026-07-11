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

variable "tags" {
  type    = map(string)
  default = {}
}
