"""Celery application configuration"""

from celery import Celery
from kombu import Queue
import os

# Import settings - handle both standalone worker and app context
try:
    from app.config import settings
    broker_url = settings.celery_broker_url
    result_backend = settings.celery_result_backend
except Exception:
    broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/1")
    result_backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

# Initialize Celery
celery_app = Celery(
    "shorts_automation",
    broker=broker_url,
    backend=result_backend,
    include=[
        "app.tasks.discovery_tasks",
        "app.tasks.analysis_tasks",
        "app.tasks.download_tasks",
        "app.tasks.editing_tasks",
    ]
)

# Celery configuration
celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    
    # Time settings
    timezone="UTC",
    enable_utc=True,
    
    # Task tracking
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max per task
    task_soft_time_limit=3000,  # 50 minute soft limit
    
    # Worker settings
    worker_prefetch_multiplier=1,  # Prevent worker from prefetching too many tasks
    worker_max_tasks_per_child=50,  # Restart worker after 50 tasks to prevent memory leaks
    
    # Task acknowledgment
    task_acks_late=True,  # Acknowledge task after completion
    task_reject_on_worker_lost=True,  # Requeue if worker dies
    
    # Results
    result_expires=86400,  # Results expire after 24 hours
    
    # Task routing
    task_routes={
        "app.tasks.discovery_tasks.*": {"queue": "discovery"},
        "app.tasks.analysis_tasks.*": {"queue": "analysis"},
        "app.tasks.download_tasks.*": {"queue": "downloads"},
        "app.tasks.editing_tasks.*": {"queue": "video_processing"},
    },
    
    # Define queues with priorities
    task_queues=(
        Queue("default", routing_key="default"),
        Queue("discovery", routing_key="discovery"),
        Queue("analysis", routing_key="analysis"),
        Queue("downloads", routing_key="downloads"),
        Queue("video_processing", routing_key="video_processing"),
    ),
    
    # Default queue
    task_default_queue="default",
)

# Celery beat schedule for periodic tasks
celery_app.conf.beat_schedule = {
    "cleanup-old-files": {
        "task": "app.tasks.download_tasks.cleanup_old_downloads",
        "schedule": 3600.0,  # Every hour
        "args": (7,),  # Days old threshold
    },
    "refresh-trending": {
        "task": "app.tasks.discovery_tasks.refresh_trending",
        "schedule": 21600.0,  # Every 6 hours
        "args": (["youtube", "tiktok", "instagram"],),
    },
}


# Task event handlers
@celery_app.task(bind=True, name="celery.ping")
def ping(self):
    """Simple ping task to test worker connectivity"""
    return "pong"


if __name__ == "__main__":
    celery_app.start()
