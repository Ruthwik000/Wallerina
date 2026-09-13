# Deploying the Wallerina backend

Two CloudFormation stacks, deployed by `deploy.sh`:

| Stack | Template | Creates |
|---|---|---|
| `wallerina-ecr` | `ecr.yaml` | ECR repositories `wallerina-api` and `wallerina-jobs` |
| `wallerina` | `wallerina.yaml` | Everything else, listed below |

The application stack creates:

- **API**: ECS Fargate service (1 vCPU, 2 GB) behind an internet-facing Application
  Load Balancer, with health checks and automatic rollback on a failed deploy.
- **Jobs**: three Lambda functions running the refresh jobs, triggered every
  5 minutes by one EventBridge rule. These are market data, prediction markets and
  wallet snapshots.
- **Simulation queue**: an SQS queue with a dead-letter queue, plus a Lambda worker
  with at most 2 concurrent simulations. It retries only the messages that failed
  for a transient reason.
- **Secret**: a Secrets Manager secret `wallerina/app` for the API keys.
- **Access**: IAM roles scoped to this stack's queue, secret, the S3 bucket and
  `rds-db:connect` for `wallerina_app`.
- **Monitoring**: log groups with 30-day retention, and alarms for dead-lettered
  jobs, API 5xx errors, no healthy API task and worker errors.

It **reuses** the existing Aurora cluster `database-1` (IAM authentication) and the
`wallerina` S3 bucket. It does not create or modify either.

## Before the first deploy

1. **Use an IAM user or role, not the root account.** It needs permissions for
   CloudFormation, ECR, ECS, ELB, EC2 security groups, Lambda, EventBridge, SQS,
   SNS, Secrets Manager, CloudWatch, Logs and IAM role creation.
2. **Install Docker and the AWS CLI v2.** The images are built for `linux/amd64`.
3. **Decide the frontend origin.** Every browser origin that calls the API must be
   listed in `CORS_ORIGINS`.
4. **Optional, for HTTPS:** request an ACM certificate in `eu-north-1` for your API
   domain and pass `CERTIFICATE_ARN`. Without it the API is served over plain HTTP.
   A frontend served over HTTPS cannot call an HTTP API because browsers block mixed
   content, so treat this as required for anything public.

## Deploy

```bash
CORS_ORIGINS=https://app.example.com \
CERTIFICATE_ARN=arn:aws:acm:eu-north-1:123456789012:certificate/... \
ALARM_EMAIL=you@example.com \
./deploy/deploy.sh
```

The script deploys the repositories and builds both images from `backend/Dockerfile`:
the `runtime` target for the API and the `lambda` target for the jobs. It then
pushes them, tagged with the git commit, and deploys the application stack into the
default VPC's public subnets. To use other networking, set `VPC_ID` and
`SUBNET_IDS`.

Re-running the script deploys a new version. ECS replaces tasks only once the new
ones pass health checks, and rolls back if they never do.

## After the first deploy

1. **Store the API keys** in the secret. Write them to a file rather than typing
   them on the command line, so they stay out of your shell history:

   ```bash
   aws secretsmanager put-secret-value --secret-id wallerina/app \
     --secret-string file://secret.json    # {"ALCHEMY_API_KEY": "...", "NVIDIA_API_KEY": "..."}
   rm secret.json
   ```

2. **Restart the API** so it reads them. Lambdas pick them up on their next cold start.

   ```bash
   aws ecs update-service --cluster <ClusterName> --service <ServiceName> --force-new-deployment
   ```

3. **Point the frontend at the API** by setting `NEXT_PUBLIC_API_URL` to the stack's
   `ApiUrl` output.
4. **Confirm the alarm subscription** email, if you set `ALARM_EMAIL`.
5. **Check the database connection:**
   `curl <ApiUrl>/health/database` should report `current_user: wallerina_app`.

## Configuration in production

The task and functions run with `APP_ENV=production`, which means:

- **Startup checks:** the API refuses to start with wildcard CORS or static AWS keys.
  Credentials come from the task and function roles.
- **Scheduled jobs:** `REFRESH_ENABLED=false` and `SIMULATION_WORKER_ENABLED=false` on
  the API, because Lambda runs the scheduled jobs and consumes the queue.
- **Rate limits:** model, simulation and wallet-scan endpoints are limited to
  `RATE_LIMIT_PER_MINUTE` (30) per client, per task. For a hard global limit, add an
  AWS WAF rate-based rule to the load balancer.
- **Refresh endpoint:** `POST /api/refresh/run` is disabled unless `ADMIN_TOKEN` is
  set. Add it to the task definition and the secret to enable it.

## Cost notes

- **Load balancer and Fargate:** a small always-on baseline, roughly $16 and $35 a
  month in most regions at one task.
- **Aurora:** the cluster auto-pauses after 5 minutes idle. The 5-minute snapshot job
  wakes it every run, so it effectively never pauses. Lengthen the schedule in
  `RefreshSchedule` if that cost matters.
- **Alchemy:** the market data job re-fetches 180 days of history for 8 assets every
  5 minutes. Check that against your Alchemy compute-unit quota.

## Teardown

```bash
aws cloudformation delete-stack --stack-name wallerina
aws cloudformation delete-stack --stack-name wallerina-ecr
```

The Aurora cluster, the S3 bucket and the manually created `wallerina-queue` are not
part of either stack and are left untouched. The stack's own queue replaces
`wallerina-queue`, which you can delete once nothing points at it.
