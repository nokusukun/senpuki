# Senpuki

**Distributed Durable Functions for Python**

Senpuki is a lightweight, asynchronous, distributed task orchestration library for Python. It enables you to write stateful, reliable workflows ("durable functions") using standard Python async/await syntax while Senpuki handles the complexity of persisting state, retrying failures, and distributing work across a pool of workers.

## Why Senpuki?

Modern distributed systems require workflows that can:

- **Survive failures** - Continue execution after crashes, restarts, or network issues
- **Scale horizontally** - Distribute work across multiple workers
- **Handle long-running operations** - Support workflows that run for hours, days, or weeks
- **Maintain consistency** - Ensure exactly-once semantics for critical operations

Senpuki provides all of this while letting you write normal Python async functions.

## Key Features

- **Durable Execution** - Workflow state is persisted to a database, surviving process restarts
- **Automatic Retries** - Configurable retry policies with exponential backoff and jitter
- **Distributed Workers** - Scale horizontally by running multiple worker processes
- **Durable Sleep** - Non-blocking waits that don't consume worker resources
- **Parallel Execution** - Fan-out/fan-in patterns with `asyncio.gather` and `Senpuki.map`
- **Rate Limiting** - Control concurrent executions per function across the cluster
- **External Signals** - Coordinate workflows with external events
- **Dead Letter Queue** - Inspect and replay failed tasks
- **Idempotency & Caching** - Prevent duplicate work and cache expensive computations
- **Multiple Backends** - SQLite for development, PostgreSQL for production
- **OpenTelemetry Integration** - Distributed tracing support
- **CLI Tools** - Inspect and manage workflows from the command line

## Quick Example

```python
import asyncio
from senpuki import Senpuki, Result

# Define a durable activity
@Senpuki.durable()
async def process_order(order_id: str) -> dict:
    # Simulate processing
    await asyncio.sleep(1)
    return {"order_id": order_id, "status": "processed"}

# Define an orchestrator workflow
@Senpuki.durable()
async def order_workflow(order_ids: list[str]) -> Result[list[dict], Exception]:
    results = []
    for order_id in order_ids:
        result = await process_order(order_id)
        results.append(result)
    return Result.Ok(results)

async def main():
    # Setup
    backend = Senpuki.backends.SQLiteBackend("workflow.db")
    await backend.init_db()
    executor = Senpuki(backend=backend)
    
    # Start worker
    worker = asyncio.create_task(executor.serve())
    
    # Dispatch workflow
    exec_id = await executor.dispatch(order_workflow, ["ORD-001", "ORD-002"])
    
    # Wait for result
    result = await executor.wait_for(exec_id)
    print(result.value)  # [{"order_id": "ORD-001", ...}, {"order_id": "ORD-002", ...}]

asyncio.run(main())
```

## Architecture Overview

```
+-------------------+       +-------------------+
|   Your App        |       |   Workers         |
|-------------------|       |-------------------|
| executor.dispatch |------>|  executor.serve   |
|                   |       |                   |
| executor.wait_for |<------|  Execute tasks    |
+-------------------+       +-------------------+
         |                           |
         v                           v
+------------------------------------------+
|            Storage Backend               |
|------------------------------------------|
|  SQLite / PostgreSQL                     |
|  - Executions, Tasks, Results            |
|  - Dead Letters, Signals, Cache          |
+------------------------------------------+
         |
         v (optional)
+------------------------------------------+
|         Redis (Notifications)            |
|------------------------------------------|
|  Pub/Sub for low-latency task updates    |
+------------------------------------------+
```

## Documentation

### Getting Started

- [Installation](getting-started.md#installation)
- [Quick Start](getting-started.md#quick-start)
- [Your First Workflow](getting-started.md#your-first-workflow)

### What's New

- [Feature Updates (019-034)](feature-updates.md)

### Core Concepts

- [Durable Functions](core-concepts.md#durable-functions)
- [Orchestrators vs Activities](core-concepts.md#orchestrators-vs-activities)
- [Executions and Tasks](core-concepts.md#executions-and-tasks)
- [Result Type](core-concepts.md#result-type)

### Guides

- [Defining Durable Functions](guides/durable-functions.md)
- [Orchestration Patterns](guides/orchestration.md)
- [Error Handling & Retries](guides/error-handling.md)
- [Parallel Execution](guides/parallel-execution.md)
- [External Signals](guides/signals.md)
- [Idempotency & Caching](guides/idempotency.md)
- [Worker Configuration](guides/workers.md)
- [Monitoring & Observability](guides/monitoring.md)

### Patterns

- [Saga Pattern](patterns/saga.md)
- [Batch Processing](patterns/batch-processing.md)

### Reference

- [Senpuki API](api-reference/senpuki.md)
- [Result API](api-reference/result.md)
- [RetryPolicy API](api-reference/retry-policy.md)
- [Backends](api-reference/backends.md)
- [Notifications](api-reference/notifications.md)
- [Configuration Reference](configuration.md)
- [Deployment Guide](deployment.md)
- [Comparison with Other Libraries](comparison.md)

## Requirements

- Python 3.12+
- `aiosqlite` (for SQLite backend)
- `asyncpg` (for PostgreSQL backend)
- `redis` (optional, for Redis notifications)

## License

MIT License

## Links

- [GitHub Repository](https://github.com/nokusukun/senpuki)
- [Issue Tracker](https://github.com/nokusukun/senpuki/issues)
