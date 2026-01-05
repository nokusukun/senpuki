# Senpuki Library Review (Principal Engineer)

## Scope
This review focuses on architecture, developer experience (DX), and production readiness risks.

## Executive Summary
Senpuki is a distributed durable-functions library for Python (conceptually similar to Temporal / Azure Durable Functions). The core architecture is promising (storage backend abstraction, retries, leases, scheduling, signals), but there are several production-critical gaps around transactional integrity, concurrency safety (especially SQLite), observability, and operational ergonomics.

Verdict:
- Prototyping / internal tooling: usable today.
- Production workloads: requires hardening work (see “Top Priority Fixes”).

---

## What’s Good
- Backend abstraction via `Backend` Protocol (`senpuki/backend/base.py:5`).
- Intuitive DX with `@Senpuki.durable()` and async workflows (`senpuki/executor.py:184`).
- Thoughtful features for a v0.x: retries/backoff, leases, delay scheduling, queues/tags, caching + idempotency, signals.
- Postgres backend uses pooled connections and row locking (`senpuki/backend/postgres.py:83`).

---

## Architecture / Design Concerns

### 1) Global Registry Singleton
File: `senpuki/registry.py:19`
- `registry` is a module-level singleton.

Risks:
- Test pollution and unpredictable behavior across test modules / processes.
- Harder multi-app embedding (shared process) and dynamic registration.

Recommendation:
- Allow `FunctionRegistry` injection into `Senpuki` instances.
- Treat “registration” as part of app bootstrap, not global ambient state.

### 2) Monkey-Patching `asyncio.sleep`
File: `senpuki/executor.py:125`
- `_patch_asyncio_sleep()` modifies `asyncio.sleep` globally.

Risks:
- Cross-cutting side effects for unrelated asyncio code.
- Breakage when multiple libraries patch asyncio primitives.
- Import-order sensitivity.

Recommendation:
- Remove global patching. Prefer one of:
  - A context manager active only during durable execution.
  - Static analysis / lint rule (best).
  - Explicit runtime check at “durable call boundaries” (warn when awaited in durable context, without patching global state).

### 3) Dynamic “wrap” / unregistered functions
File: `senpuki/executor.py:222`
- `wrap()` creates metadata but does not reliably register it.

Risks:
- Can dispatch tasks that workers cannot resolve (`registry.get(step_name)` fails).

Recommendation:
- Make behavior explicit:
  - Either require `@durable` for all remotely executed functions.
  - Or support explicit “dynamic registration” with a stable name and lifecycle.

---

## DX (Developer Experience) Issues

### 1) Dispatching Unregistered Functions Fails Silently
File: `senpuki/executor.py:512`
- When `meta` is missing, code currently does `pass`.

Risks:
- Confusing runtime errors later.

Recommendation:
- Fail fast with a clear error (e.g., `ValueError` / `RuntimeError`) including suggested fix: “decorate with `@Senpuki.durable()`”.

### 2) SQLite Backend Connection Strategy
File: `senpuki/backend/sqlite.py` (multiple methods)
- Opens a new connection per operation.

Risks:
- Significant overhead under load.
- Unclear concurrency semantics with multiple connections.

Recommendation:
- Use a persistent connection or connection pool per backend instance.

### 3) Graceful Worker Shutdown / Draining
File: `senpuki/executor.py:921`
- `serve()` loops forever with cancellation.

Risks:
- Hard to run in production (K8s termination, rolling deploys).

Recommendation:
- Add a drain/stop mechanism:
  - Stop accepting new claims.
  - Wait up to configurable timeout for in-flight tasks.
  - Expose a “health/ready” status.

---

## Production Pitfalls (Critical / High)

### CRITICAL 1) Missing Transactions for Multi-Table Writes
File: `senpuki/executor.py:581`
- `create_execution()` and `create_task()` are not atomic.

Failure mode:
- Orphan execution records if task insert fails.

Recommendation:
- Add backend-level transactional APIs (or a single method like `create_execution_with_root_task`).

### CRITICAL 2) SQLite Claim Race / Locking
File: `senpuki/backend/sqlite.py:264`
- Candidate selection and claim update are separated.

Failure mode:
- Under concurrency, multiple workers can race to claim the same task.

Recommendation:
- Use proper SQLite locking semantics (e.g., `BEGIN IMMEDIATE`) and ensure claim is atomic.
- Consider using a single statement claim pattern if possible.

### HIGH 1) Missing Indexes on Hot Paths
Files:
- `senpuki/backend/sqlite.py:init_db` and `senpuki/backend/postgres.py:init_db`

Tables are missing indexes commonly required for:
- Claim loop: `(state, scheduled_for, queue, priority)`
- Concurrency limits: `(step_name, state, lease_expires_at)`
- Execution listing: `(created_at, state)`

Failure mode:
- Performance collapse at scale; expensive full scans.

Recommendation:
- Add minimal indexes to both SQLite and Postgres schemas.

### HIGH 2) Lease Renewal for Long-Running Activities
File: `senpuki/executor.py:1017`
- No lease heartbeat/renewal while a task is executing.

Failure mode:
- Another worker can reclaim the task when lease expires and execute it again.

Recommendation:
- Add a heartbeat loop to renew lease periodically while task runs.

### HIGH 3) Database Overload Without Notification Backend
File: `senpuki/executor.py:782`
- Polling loop wakes every 100ms when Redis isn’t configured.

Failure mode:
- DB hot loop with many waiters.

Recommendation:
- Make polling adaptive/backoff-based, or strongly recommend notifications for production.

---

## Production Pitfalls (Medium)

### MEDIUM 1) Pickle Serializer Safety
File: `senpuki/utils/serialization.py:11`
- `pickle.loads()` allows arbitrary code execution.

Recommendation:
- Keep JSON default.
- Put explicit warnings in docs and ensure examples discourage pickle for untrusted persistence.

### MEDIUM 2) Dead Letter Queue (DLQ) Isn’t Operational
Files:
- `senpuki/backend/sqlite.py:418`
- `senpuki/backend/postgres.py:87`

Issues:
- Stores `str(task)` rather than structured data.
- No API to list/retry DLQ items.

Recommendation:
- Store full structured task payload and add basic DLQ management APIs.

### MEDIUM 3) Clock Skew / Time Semantics
Files:
- `senpuki/executor.py:959`

Risks:
- Leases and scheduling depend on worker wall-clock time.

Recommendation:
- Prefer DB time where possible, or document strict NTP requirements.

### MEDIUM 4) Progress Growth / Retention
File: `senpuki/core.py:65`
- Progress grows unbounded for long workflows.

Recommendation:
- Cap progress, summarize, or store progress in a separate table with retention and pagination.

---

## Codebase Maintainability

### 1) Backend Duplication
Files:
- `senpuki/backend/sqlite.py`
- `senpuki/backend/postgres.py`

Recommendation:
- Extract shared mapping/serialization logic to a shared helper module.

### 2) Type Safety / Ignored Type Checks
File: `senpuki/executor.py` (multiple `pyrefly: ignore`)

Recommendation:
- Tighten types rather than ignoring: ensure `TaskRecord.result/error` are consistently bytes-or-None and that serializer contracts are explicit.

---

## Top Priority Fixes (Order)
1. Transactional integrity for execution+root task creation.
2. Fix task-claim race and locking, especially for SQLite.
3. Add missing indexes on hot query paths.
4. Add lease renewal/heartbeat for long-running tasks.
5. Remove global `asyncio.sleep` patching.
6. Improve worker shutdown/draining.
7. Reduce DB polling load without notifications.
8. Improve DLQ operability (structured storage + API).

---

## Notes on Current Behavior Worth Documenting
- `@Senpuki.durable()` name resolution uses `module:qualname` (`senpuki/registry.py:29`). That’s stable only if code layout remains stable across deployments.
- `dispatch()` behavior with `delay` and `expiry` needs clearer semantics (expiry relative to scheduled start vs dispatch time) (`senpuki/executor.py:535`).
