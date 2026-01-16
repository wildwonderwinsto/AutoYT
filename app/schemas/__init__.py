"""Pydantic schemas package"""

from app.schemas.job import JobCreate, JobResponse, JobUpdate, JobConfig, JobStatus
from app.schemas.video import (
    PlatformContentResponse,
    VideoAnalysisResponse,
    DownloadedVideoResponse,
    OutputVideoResponse,
    DownloadRequest,
    TrendingContentResponse
)

__all__ = [
    "JobCreate",
    "JobResponse",
    "JobUpdate",
    "JobConfig",
    "JobStatus",
    "PlatformContentResponse",
    "VideoAnalysisResponse",
    "DownloadedVideoResponse",
    "OutputVideoResponse",
    "DownloadRequest",
    "TrendingContentResponse"
]
