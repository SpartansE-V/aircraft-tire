terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  backend "s3" {
    bucket         = "aircraft-tire-tfstate-442147575477"
    key            = "aircraft-tire/terraform.tfstate"
    region         = "ap-southeast-1"
    dynamodb_table = "aircraft-tire-tfstate-lock"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region
}
