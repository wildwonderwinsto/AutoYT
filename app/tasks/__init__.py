"""Celery tasks package"""

from app.tasks.discovery_tasks import start_discovery_pipeline, discover_platform
from app.tasks.analysis_tasks import analyze_videos, analyze_single_video
from app.tasks.download_tasks import download_video, batch_download
from app.tasks.editing_tasks import compile_ranking_video, render_output

__all__ = [
    "start_discovery_pipeline",
    "discover_platform",
    "analyze_videos",
    "analyze_single_video",
    "download_video",
    "batch_download",
    "compile_ranking_video",
    "render_output"
]
