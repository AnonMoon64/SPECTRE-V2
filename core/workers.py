"""Worker helpers for running blocking or long-running tasks off the GUI thread."""
from concurrent.futures import ThreadPoolExecutor, Future
import logging

logger = logging.getLogger(__name__)

# Shared executor for the application
_executor = ThreadPoolExecutor(max_workers=6)


def submit_task(fn, *args, **kwargs) -> Future:
    """Submit a callable to the shared thread pool and return a Future."""
    try:
        future = _executor.submit(fn, *args, **kwargs)
        return future
    except Exception as e:
        logger.error(f"Failed to submit task to executor: {e}")
        raise
