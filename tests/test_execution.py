import unittest
import asyncio
import os
import shutil
from dfns import DFns, Result, RetryPolicy
from dfns.backend.sqlite import SQLiteBackend
from dfns.registry import registry

# Define some test functions globally so pickle/registry can find them
@DFns.durable()
async def simple_task(x: int) -> int:
    return x * 2

@DFns.durable()
async def failing_task():
    raise ValueError("I failed")

@DFns.durable(retry_policy=RetryPolicy(max_attempts=3, initial_delay=0.01, backoff_factor=1.0))
async def retryable_task(succeed_on_attempt: int):
    pass

ATTEMPT_COUNTER = {}

@DFns.durable(retry_policy=RetryPolicy(max_attempts=4, initial_delay=0.01))
async def stateful_retry_task(exec_id_for_counter: str):
    count = ATTEMPT_COUNTER.get(exec_id_for_counter, 0) + 1
    ATTEMPT_COUNTER[exec_id_for_counter] = count
    if count < 3:
        raise ValueError(f"Fail attempt {count}")
    return count

@DFns.durable(queue="high_priority_queue", tags=["data_processing"])
async def high_priority_data_task(data: str) -> str:
    return f"Processed {data} with high priority"

@DFns.durable(queue="low_priority_queue", tags=["reporting"])
async def low_priority_report_task(report_id: str) -> str:
    return f"Generated report {report_id}"


class TestExecution(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_path = f"test_dfns_{os.getpid()}.sqlite"
        self.backend = DFns.backends.SQLiteBackend(self.db_path)
        await self.backend.init_db()
        self.executor = DFns(backend=self.backend)
        self.worker_task = asyncio.create_task(self.executor.serve(poll_interval=0.1))

    async def asyncTearDown(self):
        self.worker_task.cancel()
        try:
            await self.worker_task
        except asyncio.CancelledError:
            pass
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
            
    async def test_simple_execution(self):
        exec_id = await self.executor.dispatch(simple_task, 21)
        result = await self._wait_for_result(exec_id)
        self.assertEqual(result.value, 42)
        
    async def test_failure_execution(self):
        exec_id = await self.executor.dispatch(failing_task)
        
        # Wait for completion
        while True:
            state = await self.executor.state_of(exec_id)
            if state.state in ("completed", "failed", "timed_out"):
                break
            await asyncio.sleep(0.1)
            
        state = await self.executor.state_of(exec_id)
        self.assertEqual(state.state, "failed")
        self.assertIn("I failed", str(state.result) if state.result else str(state))
        
    async def test_retry_logic(self):
        eid = "retry_test_1"
        ATTEMPT_COUNTER[eid] = 0
        
        exec_id = await self.executor.dispatch(stateful_retry_task, eid)
        
        result = await self._wait_for_result(exec_id)
        
        self.assertEqual(result.value, 3)
        self.assertEqual(ATTEMPT_COUNTER[eid], 3)
        
        tasks = await self.backend.list_tasks_for_execution(exec_id)
        root_task = next(t for t in tasks if t.kind == "orchestrator")
        self.assertEqual(root_task.retries, 2)

    async def test_queue_and_tags_filtering(self):
        # Worker is currently serving all queues/tags by default
        # Let's create tasks for different queues
        hp_exec_id = await self.executor.dispatch(high_priority_data_task, "important_data")
        lp_exec_id = await self.executor.dispatch(low_priority_report_task, "monthly_report")

        # Stop default worker
        self.worker_task.cancel()
        try:
            await self.worker_task
        except asyncio.CancelledError:
            pass

        # Start a worker only for high_priority_queue
        hp_executor = DFns(backend=self.backend)
        hp_worker_task = asyncio.create_task(hp_executor.serve(queues=["high_priority_queue"], poll_interval=0.1))
        
        hp_result = await self._wait_for_result(hp_exec_id)
        self.assertEqual(hp_result.value, "Processed important_data with high priority")
        
        # Verify low priority task is still pending
        lp_state = await self.executor.state_of(lp_exec_id)
        self.assertEqual(lp_state.state, "pending")

        hp_worker_task.cancel()
        try:
            await hp_worker_task
        except asyncio.CancelledError:
            pass

        # Start a worker for low_priority_queue
        lp_executor = DFns(backend=self.backend)
        lp_worker_task = asyncio.create_task(lp_executor.serve(queues=["low_priority_queue"], poll_interval=0.1))
        
        lp_result = await self._wait_for_result(lp_exec_id)
        self.assertEqual(lp_result.value, "Generated report monthly_report")

        lp_worker_task.cancel()
        try:
            await lp_worker_task
        except asyncio.CancelledError:
            pass


    async def _wait_for_result(self, exec_id):
        while True:
            state = await self.executor.state_of(exec_id)
            if state.state in ("completed", "failed", "timed_out"):
                break
            await asyncio.sleep(0.1)
        return await self.executor.result_of(exec_id)