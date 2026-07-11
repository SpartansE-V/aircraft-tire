# EC2 (not Fargate - Fargate has no GPU support) capacity for GPU-accelerated
# ECS tasks. One ASG-backed capacity provider, sized for a single instance
# per the reconstructor service's always-on requirement.

data "aws_ssm_parameter" "ecs_gpu_ami" {
  name = "/aws/service/ecs/optimized-ami/amazon-linux-2/gpu/recommended"
}

resource "aws_iam_role" "ecs_instance" {
  name = "${var.project_name}-gpu-ecs-instance-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "ecs_instance" {
  role       = aws_iam_role.ecs_instance.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
}

resource "aws_iam_instance_profile" "ecs_instance" {
  name = "${var.project_name}-gpu-ecs-instance-profile"
  role = aws_iam_role.ecs_instance.name
}

resource "aws_security_group" "instances" {
  name = "${var.project_name}-gpu-instances-sg"
  # Tasks run in awsvpc mode: ALB traffic reaches each task's own ENI (the
  # "tasks" security group in the ecs module), not this host instance's
  # primary ENI. This SG only needs outbound (ECS agent registration, image
  # pulls) - no inbound rules required.
  description = "GPU ECS container instances (awsvpc mode - no inbound needed)"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

resource "aws_launch_template" "gpu" {
  name_prefix   = "${var.project_name}-gpu-"
  image_id      = jsondecode(data.aws_ssm_parameter.ecs_gpu_ami.value).image_id
  instance_type = var.instance_type

  iam_instance_profile {
    arn = aws_iam_instance_profile.ecs_instance.arn
  }

  vpc_security_group_ids = [aws_security_group.instances.id]

  user_data = base64encode(<<-EOF
    #!/bin/bash
    cat <<'CONFIG' >> /etc/ecs/ecs.config
    ECS_CLUSTER=${var.cluster_name}
    ECS_ENABLE_TASK_ENI=true
    CONFIG
  EOF
  )

  tag_specifications {
    resource_type = "instance"
    tags          = merge(var.tags, { Name = "${var.project_name}-gpu" })
  }

  tags = var.tags
}

resource "aws_autoscaling_group" "gpu" {
  name_prefix         = "${var.project_name}-gpu-"
  vpc_zone_identifier = var.subnet_ids
  min_size            = var.min_size
  max_size            = var.max_size
  desired_capacity    = var.desired_capacity
  health_check_type   = "EC2"

  # Required for ECS managed termination protection (capacity provider below).
  protect_from_scale_in = true

  launch_template {
    id      = aws_launch_template.gpu.id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = "${var.project_name}-gpu"
    propagate_at_launch = true
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_ecs_capacity_provider" "gpu" {
  name = "${var.project_name}-gpu-capacity"

  auto_scaling_group_provider {
    auto_scaling_group_arn = aws_autoscaling_group.gpu.arn

    managed_scaling {
      status          = "ENABLED"
      target_capacity = 100
    }

    managed_termination_protection = "ENABLED"
  }

  tags = var.tags
}

resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name       = var.cluster_name
  capacity_providers = [aws_ecs_capacity_provider.gpu.name]

  # Intentionally no default_capacity_provider_strategy: app/web set
  # launch_type = "FARGATE" explicitly and never fall through to this. Only
  # the reconstructor service opts in, via its own capacity_provider_strategy.
}
