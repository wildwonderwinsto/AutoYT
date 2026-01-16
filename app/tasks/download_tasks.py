"""Download Celery tasks for video fetching"""

from celery import shared_task
import structlog

from workers.celery_app import celery_app
from app.core.database import async_session_maker
from app.core.downloader import VideoDownloader
from app.models.job import Job, JobStatus
from app.models.platform_content import PlatformContent
from app.models.downloaded_video import DownloadedVideo

logger = structlog.get_logger()


@celery_app.task(bind=True, name="download.download_video")
def download_video(
    self,
    content_id: str,
    preferred_format: str = "mp4",
    preferred_resolution: str = "1080"
):
    """
    Download a single video by content ID.
    
    This task handles the actual video download with rate limiting
    and format conversion.
    """
    import asyncio
    
    async def _run():
        async with async_session_maker() as session:
            from sqlalchemy import select
            
            # Get content
            result = await session.execute(
                select(PlatformContent).where(
                    PlatformContent.content_id == content_id
                )
            )
            content = result.scalar_one_or_none()
            
            if not content:
                logger.error("Content not found", content_id=content_id)
                return {"error": "Content not found"}
            
            # Check if already downloaded
            existing = await session.execute(
                select(DownloadedVideo).where(
                    DownloadedVideo.content_id == content_id
                )
            )
            if existing.scalar_one_or_none():
                logger.info("Video already downloaded", content_id=content_id)
                return {"status": "already_downloaded", "content_id": content_id}
            
            # Download video
            downloader = VideoDownloader()
            
            logger.info(
                "Starting download",
                content_id=content_id,
                url=content.url
            )
            
            download_result = await downloader.download(
                content.url,
                str(content_id),
                preferred_format,
                preferred_resolution
            )
            
            if not download_result.success:
                logger.error(
                    "Download failed",
                    content_id=content_id,
                    error=download_result.error
                )
                return {"error": download_result.error}
            
            # Save download record
            download_record = DownloadedVideo(
                content_id=content_id,
                local_path=download_result.local_path,
                file_size_bytes=download_result.file_size_bytes,
                resolution=download_result.resolution,
                format=download_result.format,
                fps=download_result.fps,
                duration_seconds=download_result.duration_seconds
            )
            session.add(download_record)
            await session.commit()
            
            logger.info(
                "Download complete",
                content_id=content_id,
                path=download_result.local_path
            )
            
            return {
                "status": "success",
                "content_id": content_id,
                "path": download_result.local_path,
                "size_mb": download_result.file_size_bytes / (1024 * 1024)
                if download_result.file_size_bytes else 0
            }
    
    return asyncio.run(_run())


@celery_app.task(bind=True, name="download.batch_download")
def batch_download(
    self,
    content_ids: list,
    preferred_format: str = "mp4",
    preferred_resolution: str = "1080"
):
    """
    Download multiple videos by content IDs.
    
    This task orchestrates parallel downloads with progress tracking.
    """
    import asyncio
    
    async def _run():
        async with async_session_maker() as session:
            from sqlalchemy import select
            
            # Get all content
            result = await session.execute(
                select(PlatformContent).where(
                    PlatformContent.content_id.in_(content_ids)
                )
            )
            contents = result.scalars().all()
            
            if not contents:
                logger.warning("No content found for download")
                return {"error": "No content found"}
            
            downloader = VideoDownloader()
            
            # Prepare download items
            download_items = [
                {"url": c.url, "content_id": str(c.content_id)}
                for c in contents
            ]
            
            logger.info(
                "Starting batch download",
                count=len(download_items)
            )
            
            results = await downloader.batch_download(
                download_items,
                preferred_format,
                preferred_resolution
            )
            
            # Save successful downloads
            success_count = 0
            for content, download_result in zip(contents, results):
                if download_result.success:
                    download_record = DownloadedVideo(
                        content_id=content.content_id,
                        local_path=download_result.local_path,
                        file_size_bytes=download_result.file_size_bytes,
                        resolution=download_result.resolution,
                        format=download_result.format,
                        fps=download_result.fps,
                        duration_seconds=download_result.duration_seconds
                    )
                    session.add(download_record)
                    success_count += 1
            
            await session.commit()
            
            logger.info(
                "Batch download complete",
                total=len(contents),
                success=success_count
            )
            
            return {
                "total": len(contents),
                "success": success_count,
                "failed": len(contents) - success_count
            }
    
    return asyncio.run(_run())


@celery_app.task(bind=True, name="download.batch_download_for_job")
def batch_download_for_job(
    self,
    job_id: str,
    limit: int = None
):
    """
    Download all discovered videos for a job.
    
    This task is triggered after the discovery phase completes.
    """
    import asyncio
    
    async def _run():
        async with async_session_maker() as session:
            from sqlalchemy import select, desc
            
            # Get job
            job_result = await session.execute(
                select(Job).where(Job.job_id == job_id)
            )
            job = job_result.scalar_one_or_none()
            
            if not job:
                logger.error("Job not found", job_id=job_id)
                return {"error": "Job not found"}
            
            # Update status
            job.status = JobStatus.DOWNLOADING
            await session.commit()
            
            # Get content not yet downloaded
            query = (
                select(PlatformContent)
                .outerjoin(DownloadedVideo)
                .where(
                    PlatformContent.job_id == job_id,
                    DownloadedVideo.download_id.is_(None)
                )
                .order_by(desc(PlatformContent.trending_score))
            )
            
            if limit:
                query = query.limit(limit)
            
            result = await session.execute(query)
            contents = result.scalars().all()
            
            if not contents:
                logger.info("No videos to download", job_id=job_id)
                # Proceed to analysis
                from app.tasks.analysis_tasks import analyze_videos
                analyze_videos.delay(job_id)
                return {"status": "no_videos_to_download"}
            
            downloader = VideoDownloader()
            
            download_items = [
                {"url": c.url, "content_id": str(c.content_id)}
                for c in contents
            ]
            
            logger.info(
                "Starting job download",
                job_id=job_id,
                count=len(download_items)
            )
            
            # Download with progress updates
            success_count = 0
            for i, (content, item) in enumerate(zip(contents, download_items)):
                try:
                    download_result = await downloader.download(
                        item["url"],
                        item["content_id"]
                    )
                    
                    if download_result.success:
                        download_record = DownloadedVideo(
                            content_id=content.content_id,
                            local_path=download_result.local_path,
                            file_size_bytes=download_result.file_size_bytes,
                            resolution=download_result.resolution,
                            format=download_result.format,
                            fps=download_result.fps,
                            duration_seconds=download_result.duration_seconds
                        )
                        session.add(download_record)
                        success_count += 1
                    
                    # Update progress
                    self.update_state(
                        state="PROGRESS",
                        meta={
                            "current": i + 1,
                            "total": len(contents),
                            "success": success_count
                        }
                    )
                    
                except Exception as e:
                    logger.error(
                        "Download failed",
                        content_id=str(content.content_id),
                        error=str(e)
                    )
            
            await session.commit()
            
            logger.info(
                "Job downloads complete",
                job_id=job_id,
                success=success_count,
                total=len(contents)
            )
            
            # Trigger analysis
            from app.tasks.analysis_tasks import analyze_videos
            analyze_videos.delay(job_id)
            
            return {
                "job_id": job_id,
                "total": len(contents),
                "success": success_count
            }
    
    return asyncio.run(_run())


@celery_app.task(name="download.cleanup_old_downloads")
def cleanup_old_downloads(days_old: int = 7):
    """
    Clean up old downloaded videos to free storage.
    
    This is typically run on a schedule via Celery Beat.
    """
    import asyncio
    from datetime import datetime, timedelta
    import os
    
    async def _run():
        async with async_session_maker() as session:
            from sqlalchemy import select
            
            threshold = datetime.utcnow() - timedelta(days=days_old)
            
            result = await session.execute(
                select(DownloadedVideo).where(
                    DownloadedVideo.downloaded_at < threshold
                )
            )
            old_downloads = result.scalars().all()
            
            deleted_count = 0
            freed_bytes = 0
            
            for download in old_downloads:
                try:
                    if os.path.exists(download.local_path):
                        freed_bytes += os.path.getsize(download.local_path)
                        os.remove(download.local_path)
                    
                    await session.delete(download)
                    deleted_count += 1
                    
                except Exception as e:
                    logger.error(
                        "Failed to delete download",
                        download_id=str(download.download_id),
                        error=str(e)
                    )
            
            await session.commit()
            
            logger.info(
                "Cleanup complete",
                deleted=deleted_count,
                freed_mb=freed_bytes / (1024 * 1024)
            )
            
            return {
                "deleted": deleted_count,
                "freed_mb": freed_bytes / (1024 * 1024)
            }
    
    return asyncio.run(_run())
