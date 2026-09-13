"""Heavy simulations are queued, consumed by the worker, and polled for."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend import main
from backend.aws import database, handlers, queue
from backend.models.quant import SimulationRequest
from backend.services import analysis, http
from backend.services.http import UpstreamError

REQUEST = SimulationRequest(wallet_address="0x" + "c" * 40, horizon_days=365, simulations=50_000)


class TestQueueDecision:
    @pytest.mark.asyncio
    async def test_light_runs_stay_inline(self, monkeypatch):
        monkeypatch.setattr(queue, "should_queue", lambda simulations, horizon: False)

        assert await main._queue_simulation(REQUEST) is None

    @pytest.mark.asyncio
    async def test_heavy_run_is_recorded_before_it_is_queued(self, monkeypatch):
        order = []

        async def record(job_id, address, parameters):
            order.append(("record", job_id))
            return True

        def enqueue(address, **kwargs):
            order.append(("enqueue", kwargs["job_id"]))
            return kwargs["job_id"]

        monkeypatch.setattr(queue, "should_queue", lambda simulations, horizon: True)
        monkeypatch.setattr(database, "record_simulation_job", record)
        monkeypatch.setattr(queue, "enqueue_simulation", enqueue)

        job = await main._queue_simulation(REQUEST)

        assert job.status == "queued"
        assert job.status_url == f"/api/simulate/jobs/{job.job_id}"
        assert order == [("record", job.job_id), ("enqueue", job.job_id)]

    @pytest.mark.asyncio
    async def test_without_a_database_nothing_is_queued(self, monkeypatch):
        async def record(*args):
            return False

        def enqueue(*args, **kwargs):
            raise AssertionError("a job without a row must not be queued")

        monkeypatch.setattr(queue, "should_queue", lambda simulations, horizon: True)
        monkeypatch.setattr(database, "record_simulation_job", record)
        monkeypatch.setattr(queue, "enqueue_simulation", enqueue)

        assert await main._queue_simulation(REQUEST) is None

    @pytest.mark.asyncio
    async def test_a_failed_send_marks_the_job_and_runs_inline(self, monkeypatch):
        failed = []

        async def record(*args):
            return True

        async def fail(job_id, error):
            failed.append(job_id)
            return True

        monkeypatch.setattr(queue, "should_queue", lambda simulations, horizon: True)
        monkeypatch.setattr(database, "record_simulation_job", record)
        monkeypatch.setattr(database, "fail_simulation_job", fail)
        monkeypatch.setattr(queue, "enqueue_simulation", lambda *args, **kwargs: None)

        assert await main._queue_simulation(REQUEST) is None
        assert len(failed) == 1


@pytest.fixture
def worker_env(monkeypatch):
    """Stubs for the worker: records completions, failures and deletions."""
    calls = {"complete": [], "fail": [], "deleted": []}
    job = {"job_id": "job-1", "wallet_address": "0x" + "c" * 40, "horizon_days": 30, "simulations": 100}

    async def no_startup():
        return False

    async def load_estimate(address):
        return None, SimpleNamespace(total_value=1_000.0)

    async def complete(job_id, result):
        calls["complete"].append((job_id, result))
        return True

    async def fail(job_id, error):
        calls["fail"].append((job_id, error))
        return True

    monkeypatch.setattr(http, "startup", no_startup)
    monkeypatch.setattr(analysis, "load_estimate", load_estimate)
    monkeypatch.setattr(analysis, "run_simulation", lambda *a, **k: SimpleNamespace(model_dump=lambda mode: {"ok": True}))
    monkeypatch.setattr(database, "complete_simulation_job", complete)
    monkeypatch.setattr(database, "fail_simulation_job", fail)
    monkeypatch.setattr(queue, "complete_job", lambda handle: calls["deleted"].append(handle))
    monkeypatch.setattr(queue, "receive_jobs", lambda *args: [{**job, "_receipt_handle": "handle-1"}])
    return calls, job


class TestWorker:
    @pytest.mark.asyncio
    async def test_a_completed_job_is_stored_then_deleted(self, worker_env):
        calls, _ = worker_env

        summary = await handlers._run_simulation_jobs(None, wait_seconds=0)

        assert summary["processed"] == 1
        assert calls["complete"] == [("job-1", {"ok": True})]
        assert calls["deleted"] == ["handle-1"]

    @pytest.mark.asyncio
    async def test_a_job_that_cannot_succeed_is_failed_and_deleted(self, monkeypatch, worker_env):
        calls, _ = worker_env

        async def empty(address):
            raise analysis.InsufficientDataError("no priced holdings")

        monkeypatch.setattr(analysis, "load_estimate", empty)

        summary = await handlers._run_simulation_jobs(None, wait_seconds=0)

        assert summary["failed"] == 1
        assert calls["fail"][0][0] == "job-1" and "no priced holdings" in calls["fail"][0][1]
        assert calls["deleted"] == ["handle-1"]

    @pytest.mark.asyncio
    async def test_a_transient_failure_is_left_for_redelivery(self, monkeypatch, worker_env):
        calls, job = worker_env

        async def flaky(address):
            raise UpstreamError("alchemy", "timeout")

        monkeypatch.setattr(analysis, "load_estimate", flaky)
        event = {"Records": [{"messageId": "m-1", "body": __import__("json").dumps(job)}]}

        summary = await handlers._run_simulation_jobs(event)

        assert summary["retried"] == 1
        assert summary["batchItemFailures"] == [{"itemIdentifier": "m-1"}]
        assert calls["fail"] == [] and calls["deleted"] == []

    @pytest.mark.asyncio
    async def test_an_unstored_result_is_not_deleted(self, monkeypatch, worker_env):
        calls, _ = worker_env

        async def database_down(job_id, result):
            return False

        monkeypatch.setattr(database, "complete_simulation_job", database_down)

        summary = await handlers._run_simulation_jobs(None, wait_seconds=0)

        assert summary["retried"] == 1
        assert calls["deleted"] == []
