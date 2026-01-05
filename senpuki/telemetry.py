from typing import Optional
import functools
import logging
from senpuki import Senpuki

logger = logging.getLogger(__name__)

try:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode
    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False

def instrument(tracer_provider=None) -> bool:
    """
    Instruments the Senpuki library with OpenTelemetry.
    Returns True if instrumentation was installed, False otherwise.
    """
    if not _HAS_OTEL:
        logger.warning("OpenTelemetry not installed; skipping Senpuki instrumentation.")
        return False

    tracer = trace.get_tracer("senpuki", tracer_provider=tracer_provider)
    
    _instrument_executor(tracer)
    return True

def _instrument_executor(tracer):
    # Idempotency check
    if getattr(Senpuki.dispatch, "_is_otel_instrumented", False):
        return

    original_dispatch = Senpuki.dispatch
    original_handle_task = Senpuki._handle_task
    
    @functools.wraps(original_dispatch)
    async def dispatch_wrapper(self, fn, *args, **kwargs):
        # Resolve name properly if it's a wrapped function
        name = "unknown"
        if hasattr(fn, "__name__"):
            name = fn.__name__
        
        with tracer.start_as_current_span(f"senpuki.dispatch {name}", kind=trace.SpanKind.PRODUCER) as span:
            span.set_attribute("senpuki.function", name)
            
            try:
                exec_id = await original_dispatch(self, fn, *args, **kwargs)
                span.set_attribute("senpuki.execution_id", exec_id)
                return exec_id
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise

    dispatch_wrapper._is_otel_instrumented = True # pyrefly: ignore
    Senpuki.dispatch = dispatch_wrapper
    
    @functools.wraps(original_handle_task)
    async def handle_task_wrapper(self, task, worker_id, *args, **kwargs):
        # Consumer span
        with tracer.start_as_current_span(f"senpuki.execute {task.step_name}", kind=trace.SpanKind.CONSUMER) as span:
             span.set_attribute("senpuki.task_id", task.id)
             span.set_attribute("senpuki.execution_id", task.execution_id)
             span.set_attribute("senpuki.step", task.step_name)
             span.set_attribute("senpuki.worker_id", worker_id)
             
             try:
                 await original_handle_task(self, task, worker_id, *args, **kwargs)
                 
                 # Check task status after execution
                 if task.state == "failed":
                     span.set_status(Status(StatusCode.ERROR, str(task.error)))
                 elif task.state == "completed":
                     span.set_status(Status(StatusCode.OK))
                     
             except Exception as e:
                 span.record_exception(e)
                 span.set_status(Status(StatusCode.ERROR, str(e)))
                 raise

    handle_task_wrapper._is_otel_instrumented = True # pyrefly: ignore
    Senpuki._handle_task = handle_task_wrapper
