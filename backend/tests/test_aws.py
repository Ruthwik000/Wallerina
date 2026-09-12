"""Tests for the AWS layer.

The contract that matters here: every AWS integration is optional. With
AWS_ENABLED false, nothing raises and nothing blocks — the application must
behave exactly as it did before AWS existed.
"""

from __future__ import annotations

import pytest

from backend.aws import client, queue, storage, telemetry
from backend.core.config import get_settings


@pytest.fixture(autouse=True)
def clean_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestDisabledByDefault:
    def test_client_refuses_when_disabled(self, monkeypatch):
        monkeypatch.setenv("AWS_ENABLED", "false")
        get_settings.cache_clear()
        client.client.cache_clear()

        with pytest.raises(client.AwsUnavailable):
            client.client("s3")

    def test_availability_is_false_not_an_error(self, monkeypatch):
        monkeypatch.setenv("AWS_ENABLED", "false")
        get_settings.cache_clear()
        client.client.cache_clear()

        assert client.available("s3") is False


class TestStorageDegrades:
    def test_write_without_a_bucket_returns_false(self, monkeypatch):
        monkeypatch.setenv("S3_BUCKET", "")
        get_settings.cache_clear()

        assert storage.put_json("any/key.json.gz", {"a": 1}) is False

    def test_read_without_a_bucket_returns_none(self, monkeypatch):
        monkeypatch.setenv("S3_BUCKET", "")
        get_settings.cache_clear()

        assert storage.get_json("any/key.json.gz") is None

    def test_price_cache_miss_is_none(self, monkeypatch):
        monkeypatch.setenv("S3_BUCKET", "")
        get_settings.cache_clear()

        assert storage.cached_price_history("ETH") is None


class TestQueueDegrades:
    def test_nothing_is_queued_without_a_queue_url(self, monkeypatch):
        monkeypatch.setenv("SQS_QUEUE_URL", "")
        get_settings.cache_clear()

        assert queue.should_queue(200_000, 365) is False
        assert queue.enqueue_simulation("0xabc", horizon_days=365, simulations=200_000) is None
        assert queue.receive_jobs() == []

    def test_threshold_separates_heavy_from_interactive(self, monkeypatch):
        monkeypatch.setenv("SQS_QUEUE_URL", "https://sqs.example/q")
        monkeypatch.setenv("SIMULATION_QUEUE_THRESHOLD", "5000000")
        get_settings.cache_clear()

        # An interactive run stays inline; a heavy one is offloaded.
        assert queue.should_queue(5_000, 90) is False
        assert queue.should_queue(50_000, 365) is True


class TestTelemetryIsSilent:
    def test_metrics_are_dropped_when_disabled(self, monkeypatch):
        monkeypatch.setenv("CLOUDWATCH_ENABLED", "false")
        get_settings.cache_clear()

        telemetry.put_metric("Anything", 1.0)  # must not raise

    def test_timer_still_propagates_the_original_error(self, monkeypatch):
        """Telemetry must never swallow or mask an application failure."""
        monkeypatch.setenv("CLOUDWATCH_ENABLED", "false")
        get_settings.cache_clear()

        with pytest.raises(ValueError, match="boom"):
            with telemetry.timed("Thing"):
                raise ValueError("boom")


class TestSecretsPrecedence:
    def test_environment_wins_over_the_stored_secret(self, monkeypatch):
        """A locally exported key must not be overwritten by Secrets Manager."""
        from backend.aws import secrets

        monkeypatch.setenv("ALCHEMY_API_KEY", "local-value")
        monkeypatch.setenv("AWS_SECRET_ID", "")
        get_settings.cache_clear()

        assert secrets.load_into_environment() == []
        import os

        assert os.environ["ALCHEMY_API_KEY"] == "local-value"
