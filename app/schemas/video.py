"""Video Pydantic schemas"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


class PlatformContentResponse(BaseModel):
    """Schema for platform content response"""
    content_id: UUID
    job_id: Optional[UUID] = None
    platform: str
    platform_video_id: str
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    views: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    duration_seconds: Optional[int] = None
    upload_date: Optional[datetime] = None
    trending_score: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None
    discovered_at: datetime
    
    class Config:
        from_attributes = True


class TrendingContentResponse(BaseModel):
    """Schema for trending content response"""
    content_id: UUID
    platform: str
    url: str
    title: Optional[str] = None
    author: Optional[str] = None
    views: Optional[int] = None
    likes: Optional[int] = None
    trending_score: Optional[float] = None
    discovered_at: datetime
    
    class Config:
        from_attributes = True


class VideoAnalysisResponse(BaseModel):
    """Schema for video analysis response"""
    analysis_id: UUID
    content_id: UUID
    ai_model: str
    quality_score: Optional[float] = None
    virality_score: Optional[float] = None
    relevance_score: Optional[float] = None
    content_summary: Optional[str] = None
    detected_topics: Optional[List[str]] = None
    visual_analysis: Optional[Dict[str, Any]] = None
    sentiment: Optional[str] = None
    recommended: bool = False
    analyzed_at: datetime
    
    class Config:
        from_attributes = True


class DownloadRequest(BaseModel):
    """Schema for download request"""
    preferred_format: str = Field(default="mp4", pattern="^(mp4|webm|mov)$")
    preferred_resolution: str = Field(default="1080", pattern="^(480|720|1080|1440|2160)$")


class DownloadedVideoResponse(BaseModel):
    """Schema for downloaded video response"""
    download_id: UUID
    content_id: UUID
    local_path: str
    s3_path: Optional[str] = None
    file_size_bytes: Optional[int] = None
    resolution: Optional[str] = None
    format: Optional[str] = None
    fps: Optional[int] = None
    duration_seconds: Optional[float] = None
    downloaded_at: datetime
    
    class Config:
        from_attributes = True


class RankingItem(BaseModel):
    """Schema for a ranking item in output video"""
    rank: int
    content_id: UUID
    start_time: float
    end_time: float
    title: Optional[str] = None


class OutputVideoResponse(BaseModel):
    """Schema for output video response"""
    output_id: UUID
    job_id: UUID
    title: str
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    ranking_items: Optional[List[Dict[str, Any]]] = None
    local_path: str
    s3_path: Optional[str] = None
    duration_seconds: Optional[float] = None
    resolution: Optional[str] = None
    file_size_bytes: Optional[int] = None
    manual_edits: Optional[Dict[str, Any]] = None
    render_settings: Optional[Dict[str, Any]] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class OutputVideoCreate(BaseModel):
    """Schema for creating an output video"""
    job_id: UUID
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    ranking_items: List[RankingItem]
    render_settings: Optional[Dict[str, Any]] = None


class CaptionStyleConfig(BaseModel):
    """Caption style configuration"""
    font: str = "Arial-Bold"
    font_size: int = Field(default=48, ge=12, le=120)
    color: str = "white"
    stroke_color: str = "black"
    stroke_width: int = Field(default=2, ge=0, le=10)
    position_x: str = "center"
    position_y: str = "bottom"
    bg_color: Optional[str] = None
    bg_opacity: float = Field(default=0.5, ge=0.0, le=1.0)


class AudioSettingsConfig(BaseModel):
    """Audio settings configuration"""
    background_music_path: Optional[str] = None
    background_volume: float = Field(default=0.2, ge=0.0, le=1.0)
    original_audio_volume: float = Field(default=0.8, ge=0.0, le=1.0)
    fade_in_duration: float = Field(default=0.5, ge=0.0, le=5.0)
    fade_out_duration: float = Field(default=0.5, ge=0.0, le=5.0)


class RenderSettings(BaseModel):
    """Complete render settings configuration"""
    output_resolution: str = "1080x1920"
    output_fps: int = Field(default=30, ge=15, le=60)
    output_format: str = "mp4"
    transition_type: str = "fade"
    transition_duration: float = Field(default=0.3, ge=0.0, le=2.0)
    caption_style: Optional[CaptionStyleConfig] = None
    audio_settings: Optional[AudioSettingsConfig] = None
