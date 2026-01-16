"""Discovery API endpoints for content sourcing."""

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from uuid import UUID, uuid4
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.job import Job
from app.models.platform_content import PlatformContent
from app.tasks.discovery_tasks import run_discovery_job, discover_platform, start_discovery_pipeline

router = APIRouter()


class DiscoveryRequest(BaseModel):
    """Request schema for starting a discovery job."""
    niche: str = Field(..., min_length=1, max_length=100, description="Content niche to discover")
    platforms: List[Literal["youtube", "tiktok", "instagram", "snapchat"]] = Field(
        default=["youtube", "tiktok"],
        description="Platforms to search"
    )
    timeframe_hours: int = Field(
        default=720,
        ge=1,
        le=2160,
        description="How far back to search in hours (max 90 days)"
    )
    per_platform_limit: int = Field(
        default=50,
        ge=10,
        le=200,
        description="Maximum results per platform"
    )
    min_viral_score: float = Field(
        default=10.0,
        ge=0,
        le=100,
        description="Minimum viral score threshold"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "niche": "gaming highlights",
                "platforms": ["youtube", "tiktok"],
                "timeframe_hours": 168,
                "per_platform_limit": 50,
                "min_viral_score": 15.0
            }
        }


class DiscoveryResponse(BaseModel):
    """Response schema for discovery job creation."""
    message: str
    job_id: str
    celery_task_id: str
    niche: str
    platforms: List[str]
    estimated_time: str = "1-5 minutes"


class PlatformDiscoveryRequest(BaseModel):
    """Request schema for single-platform discovery."""
    platform: Literal["youtube", "tiktok", "instagram", "snapchat"]
    query: str = Field(..., min_length=1, max_length=100)
    timeframe_hours: int = Field(default=168, ge=1, le=720)
    limit: int = Field(default=50, ge=10, le=200)


class VideoPreview(BaseModel):
    """Preview of a discovered video."""
    content_id: Optional[UUID] = None
    platform: str
    title: str
    author: str
    views: int
    likes: int
    viral_score: float
    url: str
    upload_date: Optional[datetime] = None


class DiscoveryStats(BaseModel):
    """Discovery statistics."""
    total_discovered: int
    by_platform: dict
    avg_viral_score: float
    top_video: Optional[VideoPreview] = None


@router.post("/start", response_model=DiscoveryResponse)
async def start_discovery(
    request: DiscoveryRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Start a new content discovery job.
    
    This endpoint initiates async discovery across specified platforms.
    The job runs in the background and results are saved to the database.
    
    Use GET /api/v1/discovery/status/{job_id} to check progress.
    """
    # Create job record
    job_id = str(uuid4())
    
    job = Job(
        job_id=job_id,
        user_id="api_user",  # TODO: Get from auth
        job_type="discovery",
        status="pending",
        config={
            "niche": request.niche,
            "platforms": request.platforms,
            "timeframe_hours": request.timeframe_hours,
            "per_platform_limit": request.per_platform_limit,
            "min_viral_score": request.min_viral_score
        }
    )
    db.add(job)
    await db.commit()
    
    # Trigger Celery task
    task = run_discovery_job.apply_async(
        kwargs={
            "job_id": job_id,
            "niche": request.niche,
            "timeframe_hours": request.timeframe_hours,
            "platforms": request.platforms,
            "per_platform_limit": request.per_platform_limit
        },
        queue="discovery"
    )
    
    return DiscoveryResponse(
        message="Discovery job started successfully",
        job_id=job_id,
        celery_task_id=task.id,
        niche=request.niche,
        platforms=request.platforms,
        estimated_time="1-5 minutes depending on platforms"
    )


@router.get("/status/{job_id}")
async def get_discovery_status(
    job_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Get the status of a discovery job.
    
    Returns job status and count of discovered content.
    """
    result = await db.execute(select(Job).where(Job.job_id == job_id))
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Count discovered content
    content_result = await db.execute(
        select(PlatformContent).where(PlatformContent.job_id == job_id)
    )
    content_count = len(content_result.scalars().all())
    
    return {
        "job_id": str(job.job_id),
        "status": job.status,
        "niche": job.config.get("niche"),
        "platforms": job.config.get("platforms"),
        "discovered_count": content_count,
        "created_at": job.created_at,
        "error": job.error_message
    }


@router.get("/results/{job_id}", response_model=List[VideoPreview])
async def get_discovery_results(
    job_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    min_score: float = Query(0, ge=0),
    platform: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Get discovered content for a job.
    
    Returns videos sorted by viral score with optional filtering.
    """
    query = select(PlatformContent).where(
        PlatformContent.job_id == job_id,
        PlatformContent.trending_score >= min_score
    )
    
    if platform:
        query = query.where(PlatformContent.platform == platform)
    
    query = query.order_by(PlatformContent.trending_score.desc())
    query = query.offset(skip).limit(limit)
    
    result = await db.execute(query)
    content = result.scalars().all()
    
    return [
        VideoPreview(
            content_id=c.content_id,
            platform=c.platform,
            title=c.title or "",
            author=c.author or "",
            views=c.views or 0,
            likes=c.likes or 0,
            viral_score=c.trending_score or 0,
            url=c.url,
            upload_date=c.upload_date
        )
        for c in content
    ]


@router.post("/platform")
async def discover_single_platform(request: PlatformDiscoveryRequest):
    """
    Discover content from a single platform (sync preview).
    
    Returns immediately with a task ID. Use for testing or quick lookups.
    """
    task = discover_platform.apply_async(
        args=[request.platform, request.query, request.timeframe_hours, request.limit],
        queue="discovery"
    )
    
    return {
        "message": f"Discovery started for {request.platform}",
        "task_id": task.id,
        "platform": request.platform,
        "query": request.query
    }


@router.get("/stats/{job_id}", response_model=DiscoveryStats)
async def get_discovery_stats(
    job_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Get statistics for a discovery job.
    
    Returns aggregated metrics about discovered content.
    """
    result = await db.execute(
        select(PlatformContent).where(PlatformContent.job_id == job_id)
    )
    content = result.scalars().all()
    
    if not content:
        return DiscoveryStats(
            total_discovered=0,
            by_platform={},
            avg_viral_score=0.0
        )
    
    # Aggregate by platform
    by_platform = {}
    total_score = 0.0
    top_video = None
    
    for c in content:
        platform = c.platform
        by_platform[platform] = by_platform.get(platform, 0) + 1
        total_score += c.trending_score or 0
        
        if top_video is None or (c.trending_score or 0) > (top_video.viral_score or 0):
            top_video = VideoPreview(
                content_id=c.content_id,
                platform=c.platform,
                title=c.title or "",
                author=c.author or "",
                views=c.views or 0,
                likes=c.likes or 0,
                viral_score=c.trending_score or 0,
                url=c.url
            )
    
    return DiscoveryStats(
        total_discovered=len(content),
        by_platform=by_platform,
        avg_viral_score=round(total_score / len(content), 2),
        top_video=top_video
    )


@router.get("/trending")
async def get_trending_now(
    platforms: List[str] = Query(default=["youtube", "tiktok"]),
    limit: int = Query(20, ge=5, le=100),
    db: AsyncSession = Depends(get_db)
):
    """
    Get currently trending content from recent discoveries.
    
    Returns the top viral content discovered in the last 24 hours.
    """
    from datetime import timedelta
    
    cutoff = datetime.utcnow() - timedelta(hours=24)
    
    query = select(PlatformContent).where(
        PlatformContent.discovered_at >= cutoff,
        PlatformContent.platform.in_(platforms)
    ).order_by(
        PlatformContent.trending_score.desc()
    ).limit(limit)
    
    result = await db.execute(query)
    content = result.scalars().all()
    
    return {
        "trending": [
            {
                "platform": c.platform,
                "title": c.title,
                "author": c.author,
                "views": c.views,
                "viral_score": c.trending_score,
                "url": c.url
            }
            for c in content
        ],
        "count": len(content),
        "timeframe": "last 24 hours"
    }
