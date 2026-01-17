"""Celery tasks package"""

from app.tasks.discovery_tasks import start_discovery_pipeline, discover_platform
from app.tasks.analysis_tasks import process_content_pool, analyze_single_video
from app.tasks.download_tasks import download_video, batch_download
from app.tasks.editing_tasks import prepare_compilation, render_final_video

__all__ = [
    "start_discovery_pipeline",
    "discover_platform",
    "process_content_pool",
    "analyze_single_video",
    "download_video",
    "batch_download",
    "prepare_compilation",
    "render_final_video"
]
