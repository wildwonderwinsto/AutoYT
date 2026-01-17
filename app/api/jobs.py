"""Job management API endpoints"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import List, Optional
from uuid import UUID
import structlog

from app.core.database import get_db
from app.models.job import Job
from app.schemas.job import JobCreate, JobResponse, JobUpdate, JobStatus
from app.tasks.discovery_tasks import start_discovery_pipeline

router = APIRouter()
logger = structlog.get_logger()


@router.post("/", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    job_data: JobCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new automation job"""
    job = Job(
        user_id=job_data.user_id,
        job_type=job_data.job_type,
        config=job_data.config.model_dump(),
        status=JobStatus.PENDING
    )
    
    db.add(job)
    await db.commit()
    await db.refresh(job)
    
    # Trigger async discovery pipeline
    start_discovery_pipeline.delay(str(job.job_id))
    
    return job


@router.get("/", response_model=List[JobResponse])
async def list_jobs(
    user_id: Optional[str] = Query(None),
    status: Optional[JobStatus] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """List all jobs with optional filtering"""
    query = select(Job).order_by(desc(Job.created_at))
    
    if user_id:
        query = query.where(Job.user_id == user_id)
    if status:
        query = query.where(Job.status == status)
    
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get detailed job information"""
    result = await db.execute(select(Job).where(Job.job_id == job_id))
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )
    
    return job


@router.patch("/{job_id}", response_model=JobResponse)
async def update_job(
    job_id: UUID,
    job_update: JobUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update job configuration or status"""
    result = await db.execute(select(Job).where(Job.job_id == job_id))
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )
    
    update_data = job_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(job, field, value)
    
    await db.commit()
    await db.refresh(job)
    
    return job


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Cancel and delete a job"""
    result = await db.execute(select(Job).where(Job.job_id == job_id))
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )
    
    await db.delete(job)
    await db.commit()
    return None


@router.post("/{job_id}/retry", response_model=JobResponse)
async def retry_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Retry a failed job"""
    result = await db.execute(select(Job).where(Job.job_id == job_id))
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )
    
    if job.status != JobStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only failed jobs can be retried"
        )
    
    job.status = JobStatus.PENDING
    job.error_message = None
    await db.commit()
    await db.refresh(job)
    
    # Restart the pipeline
    start_discovery_pipeline.delay(str(job.job_id))
    
    return job


@router.get("/{job_id}/logs")
async def get_job_logs(
    job_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get logs for a specific job"""
    try:
        result = await db.execute(select(Job).where(Job.job_id == job_id))
        job = result.scalar_one_or_none()
        
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job {job_id} not found"
            )
        
        # Handle case where logs column might not exist yet
        logs = getattr(job, 'logs', None) or []
        
        return {
            "job_id": str(job_id),
            "status": job.status,
            "logs": logs,
            "error_message": job.error_message
        }
    except Exception as e:
        logger.error(f"Error fetching job logs: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch logs: {str(e)}"
        )
