import unittest
import asyncio
import os
import time
import logging
from dfns import DFns, Result, RetryPolicy

logging.basicConfig(level=logging.INFO)

@DFns.durable()
async def parallel_sleeper(seconds: float) -> float:
    await asyncio.sleep(seconds)
    return seconds

@DFns.durable()
async def fan_out_fan_in_workflow(count: int, sleep_time: float) -> Result[float, Exception]:
    tasks = []
    for _ in range(count):
        tasks.append(parallel_sleeper(sleep_time))
    
    # Run in parallel
    results = await asyncio.gather(*tasks)
    
    return Result.Ok(sum(results))

class TestParallel(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_path = f"test_parallel_{os.getpid()}.sqlite"
        self.backend = DFns.backends.SQLiteBackend(self.db_path)
        await self.backend.init_db()
        self.executor = DFns(backend=self.backend)
        # Increase concurrency to allow parallel execution
        self.worker_task = asyncio.create_task(self.executor.serve(poll_interval=0.1, max_concurrency=10))

    async def asyncTearDown(self):
        self.worker_task.cancel()
        try:
            await self.worker_task
        except asyncio.CancelledError:
            pass
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    async def test_parallel_execution(self):
        # We want to run 4 tasks, each sleeping 0.5s.
        # If sequential: 2.0s.
        # If parallel: ~0.5s + overhead.
        
        count = 4
        sleep_time = 0.5
        
        start_time = time.time()
        exec_id = await self.executor.dispatch(fan_out_fan_in_workflow, count, sleep_time)
        
        while True:
            state = await self.executor.state_of(exec_id)
            if state.state in ("completed", "failed", "timed_out"):
                break
            await asyncio.sleep(0.1)
            
        duration = time.time() - start_time
        result = await self.executor.result_of(exec_id)
        
        self.assertTrue(result.ok)
        self.assertEqual(result.value, count * sleep_time)
        
        # Check if it was actually parallel. 
        # Allow some overhead (e.g. 1.0s total instead of 0.5s is still better than 2.0s)
        # Overhead: DB polling (0.1s), task creation, etc.
        print(f"Total duration: {duration:.2f}s (expected < {count * sleep_time})")
        state = await self.executor.state_of(exec_id)
        print(f"Execution state progress steps: {state.progress_str}")
        for progress in state.progress:
            print(f" - {progress.step}: {progress.status} (started at {progress.started_at}, completed at {progress.completed_at})")
        self.assertLess(duration, count * sleep_time * 0.8, "Execution took too long, seemingly sequential")

