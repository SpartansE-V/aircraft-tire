# OIDC trust between GitHub Actions and this AWS account, scoped to one repo.
# Avoids long-lived AWS access keys stored as GitHub secrets.

data "tls_certificate" "github" {
  url = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
}

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github.certificates[0].sha1_fingerprint]

  tags = var.tags
}

data "aws_iam_policy_document" "github_actions_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:*"]
    }
  }
}

resource "aws_iam_role" "github_actions_deploy" {
  name               = "${var.project_name}-github-actions-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_actions_trust.json

  tags = var.tags
}

# Scoped to what the deploy workflow actually needs: push to this one ECR repo,
# read/update this one ECS service+task-family, and manage this project's
# Terraform state (bucket/key prefix + lock table).
data "aws_iam_policy_document" "github_actions_deploy" {
  statement {
    sid       = "ECRAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "ECRPush"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "ecr:PutImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
    ]
    resources = ["arn:aws:ecr:*:*:repository/${var.project_name}*"]
  }

  statement {
    sid    = "ECSDeploy"
    effect = "Allow"
    actions = [
      "ecs:DescribeServices",
      "ecs:DescribeTaskDefinition",
      "ecs:DescribeTasks",
      "ecs:ListTasks",
      "ecs:RegisterTaskDefinition",
      "ecs:UpdateService",
    ]
    resources = ["*"]
  }

  statement {
    sid     = "PassRolesToECS"
    effect  = "Allow"
    actions = ["iam:PassRole"]
    resources = [
      "arn:aws:iam::*:role/${var.project_name}*-ecs-execution-role",
      "arn:aws:iam::*:role/${var.project_name}*-ecs-task-role",
    ]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }

  statement {
    sid    = "TerraformState"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = ["arn:aws:s3:::${var.tfstate_bucket}/${var.tfstate_key_prefix}/*"]
  }

  statement {
    sid       = "TerraformStateList"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.tfstate_bucket}"]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${var.tfstate_key_prefix}/*"]
    }
  }

  statement {
    sid       = "TerraformLock"
    effect    = "Allow"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
    resources = ["arn:aws:dynamodb:${var.aws_region}:*:table/${var.tfstate_lock_table}"]
  }

  # This policy (and the role it's attached to) are part of the stack too -
  # future applies of this file need to be able to update themselves.
  statement {
    sid    = "SelfManage"
    effect = "Allow"
    actions = [
      "iam:GetRolePolicy",
      "iam:PutRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:TagRole",
      "iam:UntagRole",
    ]
    resources = [aws_iam_role.github_actions_deploy.arn]
  }

  # Terraform apply itself needs to manage the VPC/ALB/ECS/ECR/IAM resources
  # this stack owns. Kept broad (not resource-scoped) because Terraform must
  # be able to create/read/update/delete all resource types in this file set;
  # scope is still bounded to this AWS account and this role's trust policy.
  statement {
    sid    = "TerraformManageStack"
    effect = "Allow"
    actions = [
      "ec2:*Vpc*", "ec2:*Subnet*", "ec2:*RouteTable*", "ec2:*Route",
      "ec2:*InternetGateway*", "ec2:*NatGateway*", "ec2:*Eip*", "ec2:*Address*",
      "ec2:*SecurityGroup*", "ec2:DescribeAvailabilityZones", "ec2:DescribeTags",
      "ec2:CreateTags", "ec2:DeleteTags",
      "ec2:*LaunchTemplate*", "ec2:*Instances", "ec2:RunInstances",
      "ec2:TerminateInstances", "ec2:DescribeInstances", "ec2:DescribeImages",
      "elasticloadbalancing:*",
      "ecs:*",
      "ecr:*",
      "logs:*",
      "application-autoscaling:*",
      "autoscaling:*",
      "ssm:GetParameter", "ssm:GetParameters",
      "iam:GetRole", "iam:GetRolePolicy", "iam:GetOpenIDConnectProvider",
      "iam:ListRolePolicies", "iam:ListAttachedRolePolicies",
      "iam:GetInstanceProfile", "iam:ListInstanceProfilesForRole",
    ]
    resources = ["*"]
  }

  # The GPU capacity provider's EC2 instance role/profile (reconstructor
  # only) - scoped by name, same pattern as ManageECSTaskRoles below.
  statement {
    sid    = "ManageGpuInstanceRole"
    effect = "Allow"
    actions = [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:UpdateRole",
      "iam:UpdateAssumeRolePolicy",
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:CreateInstanceProfile",
      "iam:DeleteInstanceProfile",
      "iam:AddRoleToInstanceProfile",
      "iam:RemoveRoleFromInstanceProfile",
      "iam:TagInstanceProfile",
    ]
    resources = [
      "arn:aws:iam::*:role/${var.project_name}*-gpu-ecs-instance-role",
      "arn:aws:iam::*:instance-profile/${var.project_name}*-gpu-ecs-instance-profile",
    ]
  }

  # aws_iam_role_policy_attachment.ecs_instance passes the EC2 instance role
  # to launched instances - needs iam:PassRole scoped to that one role.
  statement {
    sid       = "PassGpuInstanceRole"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = ["arn:aws:iam::*:role/${var.project_name}*-gpu-ecs-instance-role"]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ec2.amazonaws.com"]
    }
  }

  # ECS task execution/task roles (one pair per service, e.g. aircraft-tire
  # and aircraft-tire-3d-reconstructor) are part of this stack too, so
  # Terraform needs full lifecycle management of them specifically (scoped
  # by name prefix, unlike the broader read-only statement above).
  statement {
    sid    = "ManageECSTaskRoles"
    effect = "Allow"
    actions = [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:UpdateRole",
      "iam:UpdateAssumeRolePolicy",
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy",
      "iam:PutRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:TagRole",
      "iam:UntagRole",
    ]
    resources = [
      "arn:aws:iam::*:role/${var.project_name}*-ecs-execution-role",
      "arn:aws:iam::*:role/${var.project_name}*-ecs-task-role",
    ]
  }

  # The uploads bucket this stack owns (name is derived from project_name +
  # account id in modules/uploads), scoped by name prefix rather than "*".
  statement {
    sid     = "ManageUploadsBucket"
    effect  = "Allow"
    actions = ["s3:*"]
    resources = [
      "arn:aws:s3:::${var.project_name}-uploads-*",
      "arn:aws:s3:::${var.project_name}-uploads-*/*",
    ]
  }
}

resource "aws_iam_role_policy" "github_actions_deploy" {
  name   = "${var.project_name}-github-actions-deploy"
  role   = aws_iam_role.github_actions_deploy.id
  policy = data.aws_iam_policy_document.github_actions_deploy.json
}
