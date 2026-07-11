variable "project_name" {
  type = string
}

variable "cluster_name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  description = "Private subnets the GPU instance(s) launch into."
  type        = list(string)
}

variable "instance_type" {
  type    = string
  default = "g4dn.2xlarge"
}

variable "min_size" {
  type    = number
  default = 1
}

variable "max_size" {
  type    = number
  default = 1
}

variable "desired_capacity" {
  type    = number
  default = 1
}

variable "tags" {
  type    = map(string)
  default = {}
}
