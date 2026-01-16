"""Rendering API endpoints for video compilation and output."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.job import Job
from app.models.output_video import OutputVideo
from app.tasks.editing_tasks import (
    render_final_video,
    render_custom_video,
    generate_preview
)

router = APIRouter()


class RenderSettings(BaseModel):
    """Configuration for video rendering."""
    voice_style: str = Field(
        default="energetic",
        description="Voice style: energetic, calm, dramatic, casual"
    )
    bg_music_selection: str = Field(
        default="default",
        description="Background music preset or path"
    )
    font_color: str = Field(default="yellow", description="Rank number color")
    font_size: int = Field(default=120, ge=48, le=200)
    caption_color: str = Field(default="white")
    caption_size: int = Field(default=48, ge=24, le=100)
    include_intro: bool = Field(default=True)
    include_outro: bool = Field(default=True)
    max_clip_duration: float = Field(default=12.0, ge=5, le=30)
    
    class Config:
        json_schema_extra = {
            "example": {
                "voice_style": "energetic",
                "font_color": "yellow",
                "font_size": 120,
                "include_intro": True
            }
        }


class CustomRenderRequest(BaseModel):
    """Request for custom video rendering."""
    content_ids: List[str] = Field(..., min_length=1, max_length=20)
    captions: Optional[Dict[str, str]] = Field(
        default=None,
        description="Map of content_id to custom caption"
    )
    settings: Optional[RenderSettings] = None


class RenderResponse(BaseModel):
    """Response for render requests."""
    message: str
    job_id: str
    task_id: str
    estimated_time: str


class OutputVideoResponse(BaseModel):
    """Output video information."""
    output_id: str
    job_id: str
    title: str
    description: Optional[str]
    tags: List[str]
    duration_seconds: float
    file_size_mb: float
    resolution: str
    local_path: str
    created_at: datetime
    status: str


@router.post("/{job_id}/render", response_model=RenderResponse)
async def start_render(
    job_id: UUID,
    settings: Optional[RenderSettings] = None,
    top_n: int = Query(10, ge=3, le=20),
    db: AsyncSession = Depends(get_db)
):
    """
    Start rendering the final video for a job.
    
    Uses AI-selected clips and generates TTS voiceovers.
    """
    # Verify job exists and is ready
    result = await db.execute(select(Job).where(Job.job_id == job_id))
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status not in ["analyzed", "discovered"]:
        raise HTTPException(
            status_code=400,
            detail=f"Job not ready for rendering (status: {job.status})"
        )
    
    # Prepare render settings
    render_settings = settings.model_dump() if settings else {}
    
    # Trigger render task
    task = render_final_video.apply_async(
        kwargs={
            "job_id": str(job_id),
            "top_n": top_n,
            "render_settings": render_settings
        },
        queue="video_processing"
    )
    
    return RenderResponse(
        message="Rendering started",
        job_id=str(job_id),
        task_id=task.id,
        estimated_time=f"{top_n * 30}-{top_n * 60} seconds"
    )


@router.post("/{job_id}/render-custom", response_model=RenderResponse)
async def render_custom(
    job_id: UUID,
    request: CustomRenderRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Render a custom video with manually selected clips.
    
    Allows custom ordering and caption overrides.
    """
    # Verify job
    result = await db.execute(select(Job).where(Job.job_id == job_id))
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    render_settings = request.settings.model_dump() if request.settings else {}
    
    task = render_custom_video.apply_async(
        kwargs={
            "job_id": str(job_id),
            "content_ids": request.content_ids,
            "captions": request.captions,
            "render_settings": render_settings
        },
        queue="video_processing"
    )
    
    return RenderResponse(
        message="Custom render started",
        job_id=str(job_id),
        task_id=task.id,
        estimated_time=f"{len(request.content_ids) * 30}-{len(request.content_ids) * 60} seconds"
    )


@router.get("/{job_id}/outputs", response_model=List[OutputVideoResponse])
async def get_job_outputs(
    job_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Get all rendered outputs for a job.
    """
    result = await db.execute(
        select(OutputVideo)
        .where(OutputVideo.job_id == job_id)
        .order_by(OutputVideo.created_at.desc())
    )
    outputs = result.scalars().all()
    
    return [
        OutputVideoResponse(
            output_id=str(o.output_id),
            job_id=str(o.job_id),
            title=o.title or "",
            description=o.description,
            tags=o.tags or [],
            duration_seconds=o.duration_seconds or 0,
            file_size_mb=round((o.file_size_bytes or 0) / (1024 * 1024), 2),
            resolution=o.resolution or "",
            local_path=o.local_path or "",
            created_at=o.created_at,
            status="ready" if o.local_path else "processing"
        )
        for o in outputs
    ]


@router.get("/output/{output_id}")
async def get_output_details(
    output_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed information about a specific output video.
    """
    result = await db.execute(
        select(OutputVideo).where(OutputVideo.output_id == output_id)
    )
    output = result.scalar_one_or_none()
    
    if not output:
        raise HTTPException(status_code=404, detail="Output not found")
    
    return {
        "output_id": str(output.output_id),
        "job_id": str(output.job_id),
        "title": output.title,
        "description": output.description,
        "tags": output.tags,
        "ranking_items": output.ranking_items,
        "duration_seconds": output.duration_seconds,
        "file_size_bytes": output.file_size_bytes,
        "resolution": output.resolution,
        "fps": output.fps,
        "local_path": output.local_path,
        "render_settings": output.render_settings,
        "created_at": output.created_at
    }


@router.get("/download/{output_id}")
async def download_output(
    output_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Download or stream the rendered video file.
    """
    result = await db.execute(
        select(OutputVideo).where(OutputVideo.output_id == output_id)
    )
    output = result.scalar_one_or_none()
    
    if not output:
        raise HTTPException(status_code=404, detail="Output not found")
    
    if not output.local_path or not Path(output.local_path).exists():
        raise HTTPException(status_code=404, detail="Video file not found")
    
    return FileResponse(
        path=output.local_path,
        filename=f"{output.title or 'video'}.mp4",
        media_type="video/mp4"
    )


@router.get("/{job_id}/preview")
async def get_render_preview(
    job_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Get a preview thumbnail for a job's render.
    """
    task = generate_preview.apply_async(
        args=[str(job_id)],
        queue="video_processing"
    )
    
    # Wait briefly for result
    try:
        result = task.get(timeout=10)
        if result.get("preview_path"):
            return FileResponse(result["preview_path"], media_type="image/jpeg")
        raise HTTPException(status_code=404, detail="Preview not available")
    except Exception:
        return {"message": "Preview generation started", "task_id": task.id}


@router.get("/{job_id}/render-status")
async def get_render_status(
    job_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Get the current rendering status for a job.
    """
    # Get job status
    job_result = await db.execute(select(Job).where(Job.job_id == job_id))
    job = job_result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Check for existing outputs
    output_result = await db.execute(
        select(OutputVideo)
        .where(OutputVideo.job_id == job_id)
        .order_by(OutputVideo.created_at.desc())
        .limit(1)
    )
    latest_output = output_result.scalar_one_or_none()
    
    return {
        "job_id": str(job_id),
        "job_status": job.status,
        "has_output": latest_output is not None,
        "latest_output": {
            "output_id": str(latest_output.output_id),
            "title": latest_output.title,
            "duration": latest_output.duration_seconds,
            "created_at": latest_output.created_at
        } if latest_output else None
    }


@router.delete("/output/{output_id}")
async def delete_output(
    output_id: UUID,
    delete_file: bool = Query(True, description="Also delete the video file"),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete an output video.
    """
    result = await db.execute(
        select(OutputVideo).where(OutputVideo.output_id == output_id)
    )
    output = result.scalar_one_or_none()
    
    if not output:
        raise HTTPException(status_code=404, detail="Output not found")
    
    # Delete file if requested
    if delete_file and output.local_path:
        try:
            Path(output.local_path).unlink(missing_ok=True)
        except Exception:
            pass
    
    await db.delete(output)
    await db.commit()
    
    return {"message": "Output deleted", "output_id": str(output_id)}


# Voice and music options endpoints

@router.get("/options/voices")
async def get_voice_options():
    """Get available voice styles for TTS."""
    return {
        "voices": [
            {
                "id": "energetic",
                "name": "Energetic Male",
                "description": "Upbeat, fast-paced voice ideal for gaming and sports content"
            },
            {
                "id": "calm",
                "name": "Calm Male",
                "description": "Steady, professional voice for educational content"
            },
            {
                "id": "dramatic",
                "name": "Dramatic Male",
                "description": "Deep, impactful voice for countdowns and reveals"
            },
            {
                "id": "casual",
                "name": "Casual Female",
                "description": "Friendly, conversational voice for lifestyle content"
            }
        ]
    }


@router.get("/options/music")
async def get_music_options():
    """Get available background music options."""
    return {
        "music": [
            {"id": "default", "name": "Upbeat Electronic", "bpm": 128},
            {"id": "epic", "name": "Epic Cinematic", "bpm": 100},
            {"id": "chill", "name": "Lo-Fi Chill", "bpm": 85},
            {"id": "hype", "name": "Trap Hype", "bpm": 140},
            {"id": "none", "name": "No Music", "bpm": 0}
        ]
    }
