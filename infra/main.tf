locals {
  tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
  }

  tfstate_bucket     = "aircraft-tire-tfstate-442147575477"
  tfstate_key_prefix = "aircraft-tire"
  tfstate_lock_table = "aircraft-tire-tfstate-lock"

  # One entry per deployable container (its own Dockerfile), sharing the
  # VPC and ECS cluster below but each getting its own ECR repo, ALB, and
  # ECS service so app/ and 3d-reconstructor/ deploy independently.
  services = {
    app = {
      name               = var.project_name
      alb_name           = var.project_name
      container_port     = 8000
      task_cpu           = 256
      task_memory        = 512
      desired_count      = 2
      image_tag          = var.image_tag_app
      health_check_path  = "/health"
      launch_type        = "FARGATE"
      gpu_count          = 0
      enable_autoscaling = true
      environment = [
        { name = "PORT", value = "8000" },
        { name = "CORS_ORIGINS", value = var.cors_origins },
      ]
    }
    reconstructor = {
      name           = "${var.project_name}-3d-reconstructor"
      alb_name       = "${var.project_name}-recon"
      container_port = 8000
      # COLMAP reconstruction is CPU/memory heavy compared to the API service.
      # Runs on EC2 (not Fargate - no GPU support) via the gpu_capacity ASG,
      # always one instance, so autoscaling the service itself is pointless.
      task_cpu           = 2048
      task_memory        = 8192
      desired_count      = 1
      image_tag          = var.image_tag_reconstructor
      environment        = [] # Dockerfile ENV defaults cover COLMAP_* config.
      health_check_path  = "/api/v1/health" # health router is mounted under api_prefix
      launch_type        = "EC2"
      gpu_count          = 1
      enable_autoscaling = false
    }
    web = {
      name               = "${var.project_name}-web"
      alb_name           = "${var.project_name}-web"
      container_port     = 80
      task_cpu           = 256
      task_memory        = 512
      desired_count      = 2
      image_tag          = var.image_tag_web
      environment        = [] # Static build; no runtime config needed.
      health_check_path  = "/health"
      launch_type        = "FARGATE"
      gpu_count          = 0
      enable_autoscaling = true
    }
  }
}

resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = local.tags
}

module "network" {
  source = "./modules/network"

  project_name = var.project_name
  vpc_cidr     = var.vpc_cidr
  azs          = var.azs
  tags         = local.tags
}

module "ecr" {
  for_each = local.services
  source   = "./modules/ecr"

  project_name = each.value.name
  tags         = local.tags
}

module "alb" {
  for_each = local.services
  source   = "./modules/alb"

  project_name      = each.value.alb_name
  vpc_id            = module.network.vpc_id
  public_subnet_ids = module.network.public_subnet_ids
  container_port    = each.value.container_port
  health_check_path = each.value.health_check_path
  tags              = local.tags
}

module "gpu_capacity" {
  source = "./modules/gpu_capacity"

  project_name     = "${var.project_name}-3d-reconstructor"
  cluster_name     = aws_ecs_cluster.main.name
  vpc_id           = module.network.vpc_id
  subnet_ids       = module.network.private_subnet_ids
  instance_type    = "g4dn.2xlarge"
  min_size         = 1
  max_size         = 1
  desired_capacity = 1
  tags             = local.tags
}

module "ecs" {
  for_each = local.services
  source   = "./modules/ecs"

  project_name           = each.value.name
  aws_region             = var.aws_region
  cluster_id             = aws_ecs_cluster.main.id
  cluster_name           = aws_ecs_cluster.main.name
  vpc_id                 = module.network.vpc_id
  private_subnet_ids     = module.network.private_subnet_ids
  alb_security_group_id  = module.alb[each.key].security_group_id
  target_group_arn       = module.alb[each.key].target_group_arn
  ecr_repository_url     = module.ecr[each.key].repository_url
  image_tag              = each.value.image_tag
  container_port         = each.value.container_port
  task_cpu               = each.value.task_cpu
  task_memory            = each.value.task_memory
  desired_count          = each.value.desired_count
  environment            = each.value.environment
  launch_type            = each.value.launch_type
  gpu_count              = each.value.gpu_count
  enable_autoscaling     = each.value.enable_autoscaling
  capacity_provider_name = each.value.launch_type == "EC2" ? module.gpu_capacity.capacity_provider_name : null
  tags                   = local.tags

  depends_on = [module.alb, module.gpu_capacity]
}

module "uploads" {
  source = "./modules/uploads"

  project_name         = var.project_name
  cors_allowed_origins = split(",", var.cors_origins)
  tags                 = local.tags
}

resource "aws_iam_role_policy" "task_uploads_access" {
  for_each = local.services

  name = "${each.value.name}-uploads-access"
  role = module.ecs[each.key].task_role_name

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
  tfstate_bucket     = local.tfstate_bucket
  tfstate_key_prefix = local.tfstate_key_prefix
  tfstate_lock_table = local.tfstate_lock_table
  tags               = local.tags
}
