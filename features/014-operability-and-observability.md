# Operability & Observability

## Description
Phase 4 focuses on making Senpuki easier to operate in production. Workers now expose explicit readiness/draining handles, the dead-letter queue stores structured payloads with CLI/API tooling, and we ship first-class observability hooks (structured logging context, optional OpenTelemetry instrumentation, and a pluggable metrics recorder).

## Key Changes
* `senpuki/executor.py` – added `WorkerLifecycle`, graceful drain handling, DLQ replay APIs, structured logging filter, and metrics callbacks for task lifecycle events.
* `senpuki/backend/sqlite.py` / `senpuki/backend/postgres.py` – persist full task payloads in `dead_tasks`, plus new list/get/delete helpers for DLQ management.
* `senpuki/cli.py` – new `dlq list|show|replay` commands for operators.
* `senpuki/metrics.py`, `senpuki/backend/utils.py` – shared helpers for metrics and DLQ serialization.
* `README.md` – documented worker lifecycle coordination, DLQ tooling, structured logging, metrics, and the no-op OpenTelemetry instrumentation behavior.

## Usage/Configuration
```python
executor = Senpuki(backend=backend, metrics=PromMetrics())
lifecycle = executor.create_worker_lifecycle(name="worker-1")
asyncio.create_task(executor.serve(lifecycle=lifecycle))
await lifecycle.wait_until_ready()

# drain on shutdown
executor.request_worker_drain(lifecycle)
await lifecycle.wait_until_stopped()

# DLQ management
letters = await executor.list_dead_letters(limit=20)
if letters:
    await executor.replay_dead_letter(letters[0].id, queue="retry")
```

CLI helpers:

```bash
senpuki dlq list
senpuki dlq show <task_id>
senpuki dlq replay <task_id> --queue retry
```

Structured logging:

```python
from senpuki import install_structured_logging
install_structured_logging()  # adds senpuki_execution_id/task_id to log records
```
