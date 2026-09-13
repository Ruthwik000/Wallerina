#!/usr/bin/env bash
# Build, push and deploy the Wallerina backend to AWS. See deploy/README.md.
#
#   CORS_ORIGINS=https://app.example.com ./deploy/deploy.sh
#
# Optional: AWS_REGION (eu-north-1), STACK_NAME (wallerina), IMAGE_TAG (git
# commit), VPC_ID and SUBNET_IDS (the default VPC), CERTIFICATE_ARN, ALARM_EMAIL,
# DESIRED_COUNT (1).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"

REGION="${AWS_REGION:-eu-north-1}"
STACK="${STACK_NAME:-wallerina}"
CORS_ORIGINS="${CORS_ORIGINS:?Set CORS_ORIGINS to the frontend origin, e.g. https://app.example.com}"

TAG="${IMAGE_TAG:-$(git -C "$ROOT" rev-parse --short HEAD)}"
if [[ -z "${IMAGE_TAG:-}" && -n "$(git -C "$ROOT" status --porcelain)" ]]; then
  # Uncommitted changes: make the tag unique so it can't be mistaken for the commit.
  TAG="$TAG-dirty-$(date +%Y%m%d%H%M%S)"
fi

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"

log() { printf '\n==> %s\n' "$*"; }

log "Container repositories (stack $STACK-ecr)"
aws cloudformation deploy --region "$REGION" --stack-name "$STACK-ecr" \
  --template-file "$HERE/ecr.yaml" --no-fail-on-empty-changeset

log "Building images $TAG"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
docker build --platform linux/amd64 --provenance=false --target runtime \
  -t "$REGISTRY/wallerina-api:$TAG" "$ROOT/backend"
docker build --platform linux/amd64 --provenance=false --target lambda \
  -t "$REGISTRY/wallerina-jobs:$TAG" "$ROOT/backend"

log "Pushing images"
docker push "$REGISTRY/wallerina-api:$TAG"
docker push "$REGISTRY/wallerina-jobs:$TAG"

VPC_ID="${VPC_ID:-$(aws ec2 describe-vpcs --region "$REGION" --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].VpcId' --output text)}"
SUBNET_IDS="${SUBNET_IDS:-$(aws ec2 describe-subnets --region "$REGION" \
  --filters "Name=vpc-id,Values=$VPC_ID" Name=default-for-az,Values=true \
  --query 'Subnets[].SubnetId' --output text | tr '\t' ',')}"

log "Application stack $STACK (VPC $VPC_ID, subnets $SUBNET_IDS)"
aws cloudformation deploy --region "$REGION" --stack-name "$STACK" \
  --template-file "$HERE/wallerina.yaml" --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
  --parameter-overrides \
    "ImageTag=$TAG" \
    "VpcId=$VPC_ID" \
    "SubnetIds=$SUBNET_IDS" \
    "CorsOrigins=$CORS_ORIGINS" \
    "CertificateArn=${CERTIFICATE_ARN:-}" \
    "AlarmEmail=${ALARM_EMAIL:-}" \
    "DesiredCount=${DESIRED_COUNT:-1}"

aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query 'Stacks[0].Outputs' --output table
