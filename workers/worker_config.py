"""Celery worker configuration and customization"""

from celery.signals import worker_ready, worker_shutdown, task_prerun, task_postrun
import structlog
import os

logger = structlog.get_logger()


@worker_ready.connect
def on_worker_ready(sender, **kwargs):
    """Called when the worker is ready to receive tasks"""
    logger.info(
        "Celery worker ready",
        hostname=sender.hostname,
        pid=os.getpid()
    )


@worker_shutdown.connect
def on_worker_shutdown(sender, **kwargs):
    """Called when the worker is shutting down"""
    logger.info(
        "Celery worker shutting down",
        hostname=sender.hostname
    )


@task_prerun.connect
def on_task_prerun(task_id, task, args, kwargs, **_):
    """Called before a task is executed"""
    logger.info(
        "Task starting",
        task_id=task_id,
        task_name=task.name,
        args=str(args)[:100]  # Truncate for logging
    )


@task_postrun.connect
def on_task_postrun(task_id, task, args, kwargs, retval, state, **_):
    """Called after a task is executed"""
    logger.info(
        "Task completed",
        task_id=task_id,
        task_name=task.name,
        state=state
    )


# Worker pool settings for different environments
WORKER_CONFIGS = {
    "default": {
        "concurrency": 4,
        "pool": "prefork",
        "loglevel": "INFO",
    },
    "discovery": {
        "concurrency": 8,  # Higher concurrency for API calls
        "pool": "prefork",
        "loglevel": "INFO",
        "queues": ["discovery"],
    },
    "analysis": {
        "concurrency": 3,  # Limited by API rate limits
        "pool": "prefork",
        "loglevel": "INFO",
        "queues": ["analysis"],
    },
    "downloads": {
        "concurrency": 5,  # Bandwidth limited
        "pool": "prefork",
        "loglevel": "INFO",
        "queues": ["downloads"],
    },
    "video_processing": {
        "concurrency": 2,  # CPU/GPU intensive
        "pool": "prefork",
        "loglevel": "INFO",
        "queues": ["video_processing"],
    },
}


def get_worker_config(worker_type: str = "default") -> dict:
    """Get worker configuration by type"""
    return WORKER_CONFIGS.get(worker_type, WORKER_CONFIGS["default"])
