"""Analysis API endpoints for video evaluation and selection."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.job import Job
from app.models.platform_content import PlatformContent
from app.models.video_analysis import VideoAnalysis
from app.models.downloaded_video import DownloadedVideo
from app.core.selector import ContentSelector, SelectionConfig
from app.tasks.analysis_tasks import process_content_pool, analyze_single_video

router = APIRouter()


class AnalysisRequest(BaseModel):
    """Request to start analysis for a job."""
    niche: str = Field(..., min_length=1, max_length=100)
    limit: int = Field(default=30, ge=5, le=100)
    
    class Config:
        json_schema_extra = {
            "example": {
                "niche": "gaming highlights",
                "limit": 30
            }
        }


class ClipScore(BaseModel):
    """Score breakdown for a clip."""
    trending: float
    quality: float
    relevance: float
    composite: float


class SelectedClip(BaseModel):
    """A selected clip for compilation."""
    clip_id: str
    rank: int
    source_url: str
    preview_path: Optional[str] = None
    title: str
    author: str
    platform: str
    suggested_caption: str
    suggested_description: str
    duration_seconds: float
    scores: ClipScore


class SelectionRequest(BaseModel):
    """Configuration for clip selection."""
    max_clips: int = Field(default=10, ge=1, le=50)
    trending_weight: float = Field(default=0.4, ge=0, le=1)
    quality_weight: float = Field(default=0.3, ge=0, le=1)
    relevance_weight: float = Field(default=0.3, ge=0, le=1)
    min_quality: float = Field(default=0.5, ge=0, le=1)
    max_per_author: int = Field(default=2, ge=1, le=10)


class AnalysisSummary(BaseModel):
    """Summary of analysis results."""
    job_id: str
    total_analyzed: int
    recommended: int
    downloaded: int
    rejection_rate: float
    avg_quality_score: float
    avg_relevance_score: float
    avg_trending_score: float


@router.post("/{job_id}/analyze")
async def start_analysis(
    job_id: UUID,
    request: AnalysisRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Start AI analysis for a job's discovered content.
    
    This triggers download and GPT-4 Vision analysis of videos.
    Progress can be tracked via the task ID.
    """
    # Verify job exists
    result = await db.execute(select(Job).where(Job.job_id == job_id))
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Count available content
    content_result = await db.execute(
        select(PlatformContent).where(PlatformContent.job_id == job_id)
    )
    content_count = len(content_result.scalars().all())
    
    if content_count == 0:
        raise HTTPException(
            status_code=400, 
            detail="No discovered content to analyze. Run discovery first."
        )
    
    # Trigger analysis task
    task = process_content_pool.apply_async(
        kwargs={
            "job_id": str(job_id),
            "niche": request.niche,
            "limit": request.limit
        },
        queue="analysis"
    )
    
    return {
        "message": "Analysis started",
        "job_id": str(job_id),
        "task_id": task.id,
        "content_to_analyze": min(content_count, request.limit),
        "estimated_time": f"{request.limit * 15}-{request.limit * 30} seconds"
    }


@router.get("/{job_id}/status")
async def get_analysis_status(
    job_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Get analysis progress and statistics for a job.
    """
    # Get job
    result = await db.execute(select(Job).where(Job.job_id == job_id))
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Count analyzed
    analyzed_result = await db.execute(
        select(VideoAnalysis)
        .join(PlatformContent)
        .where(PlatformContent.job_id == job_id)
    )
    analyzed = len(analyzed_result.scalars().all())
    
    # Count recommended
    recommended_result = await db.execute(
        select(VideoAnalysis)
        .join(PlatformContent)
        .where(
            PlatformContent.job_id == job_id,
            VideoAnalysis.recommended == True
        )
    )
    recommended = len(recommended_result.scalars().all())
    
    # Count downloaded
    downloaded_result = await db.execute(
        select(DownloadedVideo)
        .join(PlatformContent)
        .where(PlatformContent.job_id == job_id)
    )
    downloaded = len(downloaded_result.scalars().all())
    
    return {
        "job_id": str(job_id),
        "job_status": job.status,
        "analyzed": analyzed,
        "recommended": recommended,
        "downloaded": downloaded,
        "ready_for_editing": recommended > 0 and job.status == "analyzed"
    }


@router.get("/{job_id}/selected-clips", response_model=List[SelectedClip])
async def get_selected_clips(
    job_id: UUID,
    max_clips: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db)
):
    """
    Get AI-selected clips ready for compilation.
    
    Returns clips sorted by composite score with caption suggestions.
    """
    selector = ContentSelector()
    
    try:
        clips = await selector.select_top_clips(
            job_id=str(job_id),
            limit=max_clips,
            session=db
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    if not clips:
        raise HTTPException(
            status_code=404,
            detail="No recommended clips found. Run analysis first."
        )
    
    return [
        SelectedClip(
            clip_id=clip.content_id,
            rank=clip.rank,
            source_url=clip.url,
            preview_path=clip.local_path,
            title=clip.title,
            author=clip.author,
            platform=clip.platform,
            suggested_caption=clip.caption_suggestion,
            suggested_description=clip.description_suggestion,
            duration_seconds=clip.duration_seconds,
            scores=ClipScore(
                trending=clip.trending_score,
                quality=clip.quality_score,
                relevance=clip.relevance_score,
                composite=clip.composite_score
            )
        )
        for clip in clips
    ]


@router.post("/{job_id}/select-clips")
async def select_clips_custom(
    job_id: UUID,
    request: SelectionRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Select clips with custom scoring weights.
    
    Allows fine-tuning the balance between trending, quality, and relevance.
    """
    # Validate weights sum to 1
    total_weight = request.trending_weight + request.quality_weight + request.relevance_weight
    if abs(total_weight - 1.0) > 0.01:
        raise HTTPException(
            status_code=400,
            detail=f"Weights must sum to 1.0, got {total_weight}"
        )
    
    config = SelectionConfig(
        trending_weight=request.trending_weight,
        quality_weight=request.quality_weight,
        relevance_weight=request.relevance_weight,
        min_quality_score=request.min_quality,
        max_clips=request.max_clips,
        max_per_author=request.max_per_author
    )
    
    selector = ContentSelector(config)
    clips = await selector.select_top_clips(str(job_id), session=db)
    
    return {
        "selected_count": len(clips),
        "clips": [clip.to_dict() for clip in clips],
        "config_used": {
            "weights": {
                "trending": request.trending_weight,
                "quality": request.quality_weight,
                "relevance": request.relevance_weight
            },
            "limits": {
                "max_clips": request.max_clips,
                "max_per_author": request.max_per_author
            }
        }
    }


@router.get("/{job_id}/summary", response_model=AnalysisSummary)
async def get_analysis_summary(
    job_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Get summary statistics for the analysis phase.
    """
    selector = ContentSelector()
    summary = await selector.get_selection_summary(str(job_id))
    
    return AnalysisSummary(**summary)


@router.get("/{job_id}/rejections")
async def get_rejection_reasons(
    job_id: UUID,
    limit: int = Query(20, ge=1, le=100)
):
    """
    Get list of rejected videos with reasons.
    
    Useful for understanding why content was filtered out.
    """
    selector = ContentSelector()
    rejections = await selector.get_rejection_reasons(str(job_id))
    
    return {
        "job_id": str(job_id),
        "rejection_count": len(rejections),
        "rejections": rejections[:limit],
        "common_reasons": _summarize_reasons(rejections)
    }


def _summarize_reasons(rejections: List[Dict]) -> Dict[str, int]:
    """Count occurrences of each rejection reason."""
    reason_counts = {}
    
    for r in rejections:
        for reason in r.get("reasons", []):
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    
    # Sort by count
    return dict(sorted(reason_counts.items(), key=lambda x: -x[1]))


@router.post("/{job_id}/reanalyze")
async def reanalyze_with_new_niche(
    job_id: UUID,
    new_niche: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(20, ge=1, le=50)
):
    """
    Re-analyze content with a different niche context.
    
    Useful for repurposing content for different channels.
    """
    from app.tasks.analysis_tasks import reanalyze_batch
    
    task = reanalyze_batch.apply_async(
        args=[str(job_id), new_niche, limit],
        queue="analysis"
    )
    
    return {
        "message": "Re-analysis started",
        "job_id": str(job_id),
        "task_id": task.id,
        "new_niche": new_niche
    }


@router.get("/{job_id}/clip/{content_id}")
async def get_clip_details(
    job_id: UUID,
    content_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed information for a specific clip.
    """
    # Get content
    content_result = await db.execute(
        select(PlatformContent).where(
            PlatformContent.content_id == content_id,
            PlatformContent.job_id == job_id
        )
    )
    content = content_result.scalar_one_or_none()
    
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")
    
    # Get analysis
    analysis_result = await db.execute(
        select(VideoAnalysis).where(VideoAnalysis.content_id == content_id)
    )
    analysis = analysis_result.scalar_one_or_none()
    
    # Get download
    download_result = await db.execute(
        select(DownloadedVideo).where(DownloadedVideo.content_id == content_id)
    )
    download = download_result.scalar_one_or_none()
    
    return {
        "content": {
            "id": str(content.content_id),
            "url": content.url,
            "title": content.title,
            "author": content.author,
            "platform": content.platform,
            "views": content.views,
            "likes": content.likes,
            "trending_score": content.trending_score
        },
        "analysis": {
            "quality_score": analysis.quality_score if analysis else None,
            "relevance_score": analysis.relevance_score if analysis else None,
            "recommended": analysis.recommended if analysis else None,
            "sentiment": analysis.sentiment if analysis else None,
            "visual_analysis": analysis.visual_analysis if analysis else None
        } if analysis else None,
        "download": {
            "local_path": download.local_path if download else None,
            "file_size_mb": round(download.file_size_bytes / (1024*1024), 2) if download else None,
            "resolution": download.resolution if download else None,
            "duration": download.duration_seconds if download else None
        } if download else None
    }
