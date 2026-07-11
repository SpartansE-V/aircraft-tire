locals {
  tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
  }

  tfstate_bucket     = "aircraft-tire-tfstate-442147575477"
  tfstate_key_prefix = "aircraft-tire"
  tfstate_lock_table = "aircraft-tire-tfstate-lock"
}

module "network" {
  source = "./modules/network"

  project_name = var.project_name
  vpc_cidr     = var.vpc_cidr
  azs          = var.azs
  tags         = local.tags
}

module "ecr" {
  source = "./modules/ecr"

  project_name = var.project_name
  tags         = local.tags
}

module "alb" {
  source = "./modules/alb"

  project_name      = var.project_name
  vpc_id            = module.network.vpc_id
  public_subnet_ids = module.network.public_subnet_ids
  container_port    = var.container_port
  tags              = local.tags
}

module "ecs" {
  source = "./modules/ecs"

  project_name          = var.project_name
  aws_region            = var.aws_region
  vpc_id                = module.network.vpc_id
  private_subnet_ids    = module.network.private_subnet_ids
  alb_security_group_id = module.alb.security_group_id
  target_group_arn      = module.alb.target_group_arn
  ecr_repository_url    = module.ecr.repository_url
  image_tag             = var.image_tag
  container_port        = var.container_port
  task_cpu              = var.task_cpu
  task_memory           = var.task_memory
  desired_count         = var.desired_count
  cors_origins          = var.cors_origins
  tags                  = local.tags

  depends_on = [module.alb]
}

module "uploads" {
  source = "./modules/uploads"

  project_name         = var.project_name
  cors_allowed_origins = split(",", var.cors_origins)
  tags                 = local.tags
}

resource "aws_iam_role_policy" "task_uploads_access" {
  name = "${var.project_name}-uploads-access"
  role = module.ecs.task_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ListUploadsBucket"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = module.uploads.bucket_arn
      },
      {
        Sid      = "ReadWriteUploadObjects"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${module.uploads.bucket_arn}/*"
      }
    ]
  })
}

module "github_oidc" {
  source = "./modules/github_oidc"

  project_name       = var.project_name
  aws_region         = var.aws_region
  github_repo        = var.github_repo
  ecr_repository_arn = module.ecr.repository_arn
  execution_role_arn = module.ecs.execution_role_arn
  task_role_arn      = module.ecs.task_role_arn
  tfstate_bucket     = local.tfstate_bucket
  tfstate_key_prefix = local.tfstate_key_prefix
  tfstate_lock_table = local.tfstate_lock_table
  tags               = local.tags
}
