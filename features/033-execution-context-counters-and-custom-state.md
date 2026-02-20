# Execution Context Counters and Custom State

## Description
Added workflow execution context support for runtime counters and custom key-value state so durable functions can persist progress-like values and arbitrary serialized state during execution.

## Key Changes
* `senpuki/executor.py`
  * Added `Senpuki.context(...)` for accessing execution-scoped context inside durable functions.
  * `state_of(...)` now returns `counters` and `custom_state` when available.
* `senpuki/executor_context.py`
  * Added `ExecutionContext` with:
    * `ctx.counters(name).add(amount)`
    * `ctx.state(key).set(value)`
  * Added async operation tracking and flush-on-task-finalization support.
* `senpuki/executor_worker.py`
  * Binds and flushes execution context around task execution to persist context updates.
* `senpuki/backend/base.py`
  * Added backend protocol methods for execution counters and custom state storage.
* `senpuki/backend/sqlite.py`
  * Added `execution_counters` and `execution_state` tables and CRUD helpers.
  * Extended cleanup to remove execution context rows with execution deletion.
* `senpuki/backend/postgres.py`
  * Added `execution_counters` and `execution_state` tables and CRUD helpers.
  * Extended cleanup to remove execution context rows with execution deletion.
* `senpuki/core.py`
  * Extended `ExecutionState` with `counters` and `custom_state` fields.
* `tests/test_context.py`
  * Added regression coverage for initializing counters/state, nested updates, and `state_of` visibility.

## Usage/Configuration
```python
@Senpuki.durable()
async def bar():
    ctx = Senpuki.context()
    ctx.counters("progress").add(1)
    ctx.counters("abc").add(40)
    ctx.state("phase").set("bar_done")


@Senpuki.durable()
async def foo():
    ctx = Senpuki.context(counters={"progress": 0, "volume": 30}, state={"owner": "foo"})
    await bar()


# Later
state = await executor.state_of(execution_id)
print(state.counters)
print(state.custom_state)
```
