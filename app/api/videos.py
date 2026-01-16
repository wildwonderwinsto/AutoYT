"""Video management API endpoints"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import List, Optional
from uuid import UUID

from app.core.database import get_db
from app.models.platform_content import PlatformContent
from app.models.video_analysis import VideoAnalysis
from app.models.downloaded_video import DownloadedVideo
from app.models.output_video import OutputVideo
from app.schemas.video import (
    PlatformContentResponse,
    VideoAnalysisResponse,
    DownloadedVideoResponse,
    OutputVideoResponse,
    DownloadRequest
)
from app.tasks.download_tasks import download_video

router = APIRouter()


@router.get("/content", response_model=List[PlatformContentResponse])
async def list_platform_content(
    job_id: Optional[UUID] = Query(None),
    platform: Optional[str] = Query(None),
    recommended: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """List discovered platform content with filtering"""
    query = select(PlatformContent).order_by(desc(PlatformContent.trending_score))
    
    if job_id:
        query = query.where(PlatformContent.job_id == job_id)
    if platform:
        query = query.where(PlatformContent.platform == platform)
    
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/content/{content_id}", response_model=PlatformContentResponse)
async def get_platform_content(
    content_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get detailed platform content information"""
    result = await db.execute(
        select(PlatformContent).where(PlatformContent.content_id == content_id)
    )
    content = result.scalar_one_or_none()
    
    if not content:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Content {content_id} not found"
        )
    
    return content


@router.get("/content/{content_id}/analysis", response_model=VideoAnalysisResponse)
async def get_video_analysis(
    content_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get AI analysis results for a video"""
    result = await db.execute(
        select(VideoAnalysis).where(VideoAnalysis.content_id == content_id)
    )
    analysis = result.scalar_one_or_none()
    
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis for content {content_id} not found"
        )
    
    return analysis


@router.post("/content/{content_id}/download", response_model=DownloadedVideoResponse)
async def trigger_download(
    content_id: UUID,
    request: DownloadRequest,
    db: AsyncSession = Depends(get_db)
):
    """Trigger video download for a content item"""
    result = await db.execute(
        select(PlatformContent).where(PlatformContent.content_id == content_id)
    )
    content = result.scalar_one_or_none()
    
    if not content:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Content {content_id} not found"
        )
    
    # Check if already downloaded
    existing = await db.execute(
        select(DownloadedVideo).where(DownloadedVideo.content_id == content_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Video already downloaded"
        )
    
    # Trigger async download
    download_video.delay(
        str(content_id),
        request.preferred_format,
        request.preferred_resolution
    )
    
    return {
        "message": "Download initiated",
        "content_id": content_id,
        "status": "processing"
    }


@router.get("/downloads", response_model=List[DownloadedVideoResponse])
async def list_downloads(
    job_id: Optional[UUID] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """List downloaded videos"""
    query = select(DownloadedVideo).order_by(desc(DownloadedVideo.downloaded_at))
    
    if job_id:
        query = query.join(PlatformContent).where(PlatformContent.job_id == job_id)
    
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/outputs", response_model=List[OutputVideoResponse])
async def list_output_videos(
    job_id: Optional[UUID] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """List compiled output videos"""
    query = select(OutputVideo).order_by(desc(OutputVideo.created_at))
    
    if job_id:
        query = query.where(OutputVideo.job_id == job_id)
    
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/outputs/{output_id}", response_model=OutputVideoResponse)
async def get_output_video(
    output_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get detailed output video information"""
    result = await db.execute(
        select(OutputVideo).where(OutputVideo.output_id == output_id)
    )
    output = result.scalar_one_or_none()
    
    if not output:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output video {output_id} not found"
        )
    
    return output
