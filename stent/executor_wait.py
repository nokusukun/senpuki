from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Awaitable, Callable

from stent.core import ExecutionState, TaskRecord
from stent.notifications.base import NotificationBackend

TASK_TERMINAL_STATES = ("completed", "failed")
EXECUTION_TERMINAL_STATES = ("completed", "failed", "timed_out", "cancelled")


async def wait_for_task_terminal(
    *,
    task_id: str,
    get_task: Callable[[str], Awaitable[TaskRecord | None]],
    notification_backend: NotificationBackend | None,
    expiry: float | None,
    poll_min_interval: float,
    poll_max_interval: float,
    poll_backoff_factor: float,
    sleep_fn: Callable[[float], Awaitable[None]],
    expiry_error_factory: Callable[[str], Exception],
) -> TaskRecord:
    if notification_backend:
        return await _wait_task_with_notifications(
            task_id=task_id,
            get_task=get_task,
            notification_backend=notification_backend,
            expiry=expiry,
            poll_min_interval=poll_min_interval,
            poll_max_interval=poll_max_interval,
            poll_backoff_factor=poll_backoff_factor,
            sleep_fn=sleep_fn,
            expiry_error_factory=expiry_error_factory,
        )

    start = datetime.now()
    delay = poll_min_interval
    while True:
        task = await get_task(task_id)
        if task and task.state in TASK_TERMINAL_STATES:
            return task
        if expiry and (datetime.now() - start).total_seconds() > expiry:
            raise expiry_error_factory(f"Task {task_id} timed out")
        await sleep_fn(delay)
        delay = min(poll_max_interval, delay * poll_backoff_factor)


async def _wait_task_with_notifications(
    *,
    task_id: str,
    get_task: Callable[[str], Awaitable[TaskRecord | None]],
    notification_backend: NotificationBackend,
    expiry: float | None,
    poll_min_interval: float,
    poll_max_interval: float,
    poll_backoff_factor: float,
    sleep_fn: Callable[[float], Awaitable[None]],
    expiry_error_factory: Callable[[str], Exception],
) -> TaskRecord:
    start = datetime.now()
    delay = poll_min_interval

    # Start listening before the first DB check to avoid a race where the task
    # completes between our check and the subscribe call.
    notification_iter = notification_backend.subscribe_to_task(task_id, expiry=expiry)

    # Wrap the async iterator so we can race it against a poll timer.
    notification_queue: asyncio.Queue[bool] = asyncio.Queue()
    notification_done = False

    async def _drain_notifications() -> None:
        nonlocal notification_done
        try:
            async for _ in notification_iter:
                notification_queue.put_nowait(True)
        except asyncio.TimeoutError:
            pass
        except asyncio.CancelledError:
            return
        finally:
            notification_done = True
            notification_queue.put_nowait(False)  # wake up the main loop

    drain_task = asyncio.ensure_future(_drain_notifications())

    try:
        while True:
            # Check DB on every wake-up (notification or poll timer).
            task = await get_task(task_id)
            if task and task.state in TASK_TERMINAL_STATES:
                return task

            if expiry and (datetime.now() - start).total_seconds() > expiry:
                raise expiry_error_factory(f"Task {task_id} timed out")

            if notification_done:
                # Notifications ended without a terminal state — fall through
                # to a final DB check, then raise.
                task = await get_task(task_id)
                if task and task.state in TASK_TERMINAL_STATES:
                    return task
                raise expiry_error_factory(f"Task {task_id} timed out")

            # Wait for either a notification or the poll timer to fire.
            poll_sleep = asyncio.ensure_future(sleep_fn(delay))
            notify_wait = asyncio.ensure_future(notification_queue.get())
            done, pending = await asyncio.wait(
                [poll_sleep, notify_wait],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for p in pending:
                p.cancel()

            delay = min(poll_max_interval, delay * poll_backoff_factor)
    finally:
        drain_task.cancel()
        try:
            await drain_task
        except asyncio.CancelledError:
            pass


async def wait_for_execution_terminal(
    *,
    execution_id: str,
    state_of: Callable[[str], Awaitable[ExecutionState]],
    notification_backend: NotificationBackend | None,
    expiry: float | None,
    sleep_interval: float,
    expiry_error_factory: Callable[[str], Exception],
) -> ExecutionState:
    if notification_backend:
        return await _wait_execution_with_notifications(
            execution_id=execution_id,
            state_of=state_of,
            notification_backend=notification_backend,
            expiry=expiry,
            sleep_interval=sleep_interval,
            expiry_error_factory=expiry_error_factory,
        )

    start = datetime.now()
    while True:
        state = await state_of(execution_id)
        if state.state in EXECUTION_TERMINAL_STATES:
            return state

        if expiry and (datetime.now() - start).total_seconds() > expiry:
            raise expiry_error_factory(f"Timed out waiting for execution {execution_id}")

        await asyncio.sleep(sleep_interval)


async def _wait_execution_with_notifications(
    *,
    execution_id: str,
    state_of: Callable[[str], Awaitable[ExecutionState]],
    notification_backend: NotificationBackend,
    expiry: float | None,
    sleep_interval: float,
    expiry_error_factory: Callable[[str], Exception],
) -> ExecutionState:
    start = datetime.now()

    notification_iter = notification_backend.subscribe_to_execution(execution_id, expiry=expiry)

    notification_queue: asyncio.Queue[bool] = asyncio.Queue()
    notification_done = False

    async def _drain_notifications() -> None:
        nonlocal notification_done
        try:
            async for _ in notification_iter:
                notification_queue.put_nowait(True)
        except asyncio.TimeoutError:
            pass
        except asyncio.CancelledError:
            return
        finally:
            notification_done = True
            notification_queue.put_nowait(False)

    drain_task = asyncio.ensure_future(_drain_notifications())

    try:
        while True:
            state = await state_of(execution_id)
            if state.state in EXECUTION_TERMINAL_STATES:
                return state

            if expiry and (datetime.now() - start).total_seconds() > expiry:
                raise expiry_error_factory(f"Timed out waiting for execution {execution_id}")

            if notification_done:
                state = await state_of(execution_id)
                if state.state in EXECUTION_TERMINAL_STATES:
                    return state
                raise expiry_error_factory(f"Timed out waiting for execution {execution_id}")

            poll_sleep = asyncio.ensure_future(asyncio.sleep(sleep_interval))
            notify_wait = asyncio.ensure_future(notification_queue.get())
            done, pending = await asyncio.wait(
                [poll_sleep, notify_wait],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for p in pending:
                p.cancel()
    finally:
        drain_task.cancel()
        try:
            await drain_task
        except asyncio.CancelledError:
            pass
