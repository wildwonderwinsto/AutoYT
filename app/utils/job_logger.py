"""Utility for logging job activities to the database."""

from datetime import datetime
from typing import Optional, Dict, Any, Union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
import json
import uuid

from app.models.job import Job


async def add_job_log(
    session: AsyncSession,
    job_id: Union[str, uuid.UUID],
    level: str,  # 'info', 'warning', 'error', 'success'
    message: str,
    details: Optional[Dict[str, Any]] = None
) -> None:
    """
    Add a log entry to a job's logs array.
    
    Args:
        session: Database session
        job_id: Job UUID
        level: Log level (info, warning, error, success)
        message: Log message
        details: Optional additional details as dict
    
    Returns silently if logs column doesn't exist yet.
    """
    try:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "message": message,
            "details": details or {}
        }
        
        # Convert string UUID to UUID object if needed
        if isinstance(job_id, str):
            job_id = uuid.UUID(job_id)
        
        # Check if logs column exists by trying to access it
        # If it doesn't exist, this will fail gracefully
        from sqlalchemy.exc import ProgrammingError
        
        try:
            # Get current logs
            result = await session.execute(
                select(Job.logs).where(Job.job_id == job_id)
            )
            current_logs = result.scalar_one_or_none() or []
            
            # Append new log entry
            updated_logs = current_logs + [log_entry]
            
            # Update job with new logs
            await session.execute(
                update(Job)
                .where(Job.job_id == job_id)
                .values(logs=updated_logs)
            )
        except ProgrammingError as e:
            # Column doesn't exist yet - rollback and continue
            await session.rollback()
            # Log to console as fallback
            import structlog
            logger = structlog.get_logger()
            logger.warning(
                "Cannot log to database - logs column doesn't exist",
                job_id=str(job_id),
                level=level,
                message=message
            )
    except Exception as e:
        # Don't let logging failures break the job
        await session.rollback()
        import structlog
        logger = structlog.get_logger()
        logger.warning(f"Failed to add job log: {e}", job_id=str(job_id))


async def get_job_logs(session: AsyncSession, job_id: Union[str, uuid.UUID]) -> list:
    """Get all logs for a job."""
    # Convert string UUID to UUID object if needed
    if isinstance(job_id, str):
        job_id = uuid.UUID(job_id)
    
    result = await session.execute(
        select(Job.logs).where(Job.job_id == job_id)
    )
    logs = result.scalar_one_or_none() or []
    return logs
