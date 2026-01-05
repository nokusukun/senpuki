# Transactional Backend Hardening

## Description
Phase 1 of the hardening plan focuses on preventing duplicate or orphaned work. Executors now create executions and their root tasks atomically, SQLite task claiming is serialized under contention, and both backends gained the indexes needed for their hottest query paths.

## Key Changes
* Added `Backend.create_execution_with_root_task()` and implemented it for SQLite/Postgres so dispatch failures cannot leave orphaned executions or tasks.
* Introduced transactional helpers plus tests that prove the SQLite backend rolls back when a root task insert fails mid-dispatch.
* Reworked SQLite task claiming to use `BEGIN IMMEDIATE` transactions that lock the queue until a task is committed, and tightened concurrency-limit enforcement with multi-worker stress coverage.
* Created indexes for task-queue scans, execution lookups, and concurrency-limit queries in both backends to keep claims, counts, and list operations fast under load.

## Usage/Configuration
Third-party backends must implement the new atomic creation hook. A minimal example:

```python
class CustomBackend:
    async def create_execution_with_root_task(self, record, task):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await self._insert_execution(conn, record)
                await self._insert_task(conn, task)
```

Existing executors automatically use the method when available and fall back to the legacy two-step insert when a backend has not been updated yet.
