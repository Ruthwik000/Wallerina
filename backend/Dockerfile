# Wallerina backend — image for ECS / Fargate.
#
# Multi-stage so the runtime layer carries no build toolchain. Runs as a
# non-root user, which ECS task definitions should enforce anyway.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Dependencies resolve in their own layer, so application edits don't
# invalidate the install on every build.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

COPY src ./src
RUN uv sync --frozen --no-dev --no-editable


# Lambda image for the scheduled jobs and the queue worker: the same code and
# locked dependencies on the Lambda Python runtime. Each function picks its
# handler (ImageConfig.Command in deploy/wallerina.yaml). Build it with
# --target lambda --provenance=false; Lambda rejects multi-manifest images.
FROM public.ecr.aws/lambda/python:3.12 AS lambda

COPY --from=build /app/.venv/lib/python3.12/site-packages ${LAMBDA_TASK_ROOT}

CMD ["backend.aws.handlers.refresh_market_data"]


# The API image for ECS / Fargate (the default target).
FROM python:3.12-slim-bookworm AS runtime

RUN useradd --create-home --uid 10001 wallerina
WORKDIR /app

COPY --from=build --chown=wallerina:wallerina /app/.venv /app/.venv
COPY --from=build --chown=wallerina:wallerina /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER wallerina
EXPOSE 8000

# Logs go to stdout; the awslogs driver forwards them to CloudWatch.
# Credentials come from the task role, not from a baked-in .env.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
