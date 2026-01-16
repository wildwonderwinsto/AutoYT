"""Job Pydantic schemas"""

from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime
from uuid import UUID
from enum import Enum


class JobStatus(str, Enum):
    PENDING = "pending"
    DISCOVERING = "discovering"
    ANALYZING = "analyzing"
    DOWNLOADING = "downloading"
    EDITING = "editing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobType(str, Enum):
    RANKING = "ranking"
    COMPILATION = "compilation"
    HIGHLIGHTS = "highlights"


class JobConfig(BaseModel):
    """Job configuration schema"""
    niche: str = Field(..., min_length=1, max_length=100)
    platforms: List[Literal["youtube", "tiktok", "instagram", "snapchat"]] = Field(
        default=["youtube", "tiktok"]
    )
    timeframe: Literal["1h", "6h", "12h", "24h", "7d", "30d"] = "24h"
    max_videos: int = Field(default=100, ge=10, le=500)
    min_quality_score: float = Field(default=0.6, ge=0.0, le=1.0)
    min_virality_score: float = Field(default=0.5, ge=0.0, le=1.0)
    min_relevance_score: float = Field(default=0.7, ge=0.0, le=1.0)
    output_settings: Optional[dict] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "niche": "gaming",
                "platforms": ["youtube", "tiktok"],
                "timeframe": "24h",
                "max_videos": 100,
                "min_quality_score": 0.6,
                "min_virality_score": 0.5,
                "min_relevance_score": 0.7
            }
        }


class JobCreate(BaseModel):
    """Schema for creating a new job"""
    user_id: str = Field(..., min_length=1, max_length=255)
    job_type: JobType = JobType.RANKING
    config: JobConfig
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "user-123",
                "job_type": "ranking",
                "config": {
                    "niche": "gaming",
                    "platforms": ["youtube", "tiktok"],
                    "timeframe": "24h",
                    "max_videos": 100
                }
            }
        }


class JobUpdate(BaseModel):
    """Schema for updating a job"""
    status: Optional[JobStatus] = None
    config: Optional[JobConfig] = None
    error_message: Optional[str] = None


class JobResponse(BaseModel):
    """Schema for job response"""
    job_id: UUID
    user_id: str
    job_type: str
    status: str
    config: dict
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    
    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "job_id": "123e4567-e89b-12d3-a456-426614174000",
                "user_id": "user-123",
                "job_type": "ranking",
                "status": "pending",
                "config": {
                    "niche": "gaming",
                    "platforms": ["youtube", "tiktok"]
                },
                "created_at": "2024-01-15T10:00:00Z",
                "updated_at": "2024-01-15T10:00:00Z"
            }
        }


class JobProgress(BaseModel):
    """Schema for job progress tracking"""
    job_id: UUID
    status: JobStatus
    stage: str
    progress_percent: float = Field(ge=0, le=100)
    current_task: Optional[str] = None
    videos_discovered: int = 0
    videos_analyzed: int = 0
    videos_downloaded: int = 0
    estimated_completion: Optional[datetime] = None
