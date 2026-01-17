"""Analysis Celery tasks for video evaluation."""

from celery import shared_task
from datetime import datetime
import asyncio
import os
import structlog

from workers.celery_app import celery_app
from app.core.database import async_session_maker
from app.utils.async_utils import run_async

logger = structlog.get_logger()


@celery_app.task(bind=True, name="analysis.process_content_pool")
def process_content_pool(
    self,
    job_id: str,
    niche: str,
    limit: int = 30
):
    """
    Main analysis task that downloads and analyzes videos.
    
    Pipeline:
    1. Fetch discovered videos from database
    2. Download video files
    3. Run quality checks
    4. AI vision analysis
    5. Save results and update recommendations
    
    Args:
        job_id: Job UUID
        niche: Content niche for relevance scoring
        limit: Maximum videos to process
    """
    import asyncio
    
    async def _process():
        from sqlalchemy import select, update, text
        from app.core.downloader import VideoDownloader
        from app.core.analyzer.vision_analyzer import VisionAnalyzer
        from app.core.analyzer.quality_checker import QualityChecker
        from app.models.job import Job, JobStatus
        from app.models.platform_content import PlatformContent
        from app.models.video_analysis import VideoAnalysis
        from app.models.downloaded_video import DownloadedVideo
        
        async with async_session_maker() as session:
            try:
                # Update job status
                await session.execute(
                    update(Job)
                    .where(Job.job_id == job_id)
                    .values(status=JobStatus.ANALYZING)
                )
                await session.commit()
                
                # Initialize components
                downloader = VideoDownloader()
                from app.config import settings
                analyzer = VisionAnalyzer(use_free=settings.use_free_analyzer)
                quality_checker = QualityChecker()
                
                # Fetch top discovered content
                result = await session.execute(
                    select(PlatformContent)
                    .where(PlatformContent.job_id == job_id)
                    .order_by(PlatformContent.trending_score.desc())
                    .limit(limit)
                )
                content_list = result.scalars().all()
                
                logger.info(
                    f"Processing {len(content_list)} videos",
                    job_id=job_id,
                    niche=niche
                )
                
                processed = 0
                downloaded = 0
                analyzed = 0
                recommended = 0
                
                for i, content in enumerate(content_list):
                    try:
                        # Update progress
                        self.update_state(
                            state="PROGRESS",
                            meta={
                                "current": i + 1,
                                "total": len(content_list),
                                "stage": "processing",
                                "downloaded": downloaded,
                                "analyzed": analyzed
                            }
                        )
                        
                        # Check if already processed
                        existing_analysis = await session.execute(
                            select(VideoAnalysis)
                            .where(VideoAnalysis.content_id == content.content_id)
                        )
                        if existing_analysis.scalar_one_or_none():
                            processed += 1
                            continue
                        
                        # Download video
                        download_result = await downloader.download_video(
                            url=content.url,
                            video_id=content.platform_video_id,
                            content_id=str(content.content_id)
                        )
                        
                        if not download_result.success:
                            logger.warning(
                                f"Download failed: {content.content_id}",
                                error=download_result.error
                            )
                            continue
                        
                        downloaded += 1
                        local_path = download_result.local_path
                        
                        # Save download record
                        download_record = DownloadedVideo(
                            content_id=content.content_id,
                            local_path=local_path,
                            file_size_bytes=download_result.file_size_bytes,
                            resolution=download_result.resolution,
                            format=download_result.format,
                            fps=download_result.fps,
                            duration_seconds=download_result.duration_seconds
                        )
                        session.add(download_record)
                        
                        # Quick quality check first
                        quality_report = quality_checker.check_video(local_path)
                        
                        if not quality_report.passed:
                            # Create analysis record marked as not recommended
                            analysis = VideoAnalysis(
                                content_id=content.content_id,
                                ai_model="quality_check",
                                quality_score=0.0,
                                relevance_score=0.0,
                                visual_analysis={
                                    "quality_check_failed": True,
                                    "issues": quality_report.issues,
                                    "rejection_reasons": quality_report.issues
                                },
                                recommended=False
                            )
                            session.add(analysis)
                            processed += 1
                            continue
                        
                        # AI Vision Analysis
                        try:
                            # Pass metadata for free analyzer
                            video_metadata = {
                                "title": content.title,
                                "description": content.description,
                                "views": content.views or 0,
                                "likes": content.likes or 0,
                                "comments": content.comments or 0,
                                "upload_date": content.upload_date
                            }
                            analysis_result = await analyzer.analyze_video(
                                video_path=local_path,
                                niche_context=niche,
                                content_id=str(content.content_id),
                                metadata=video_metadata
                            )
                            analyzed += 1
                            
                            # Save analysis
                            from app.config import settings
                            model_name = "free-vision" if settings.use_free_analyzer else "gpt-4-vision"
                            analysis = VideoAnalysis(
                                content_id=content.content_id,
                                ai_model=model_name,
                                quality_score=analysis_result.visual_quality_score,
                                relevance_score=analysis_result.relevance_score,
                                virality_score=analysis_result.virality_potential,
                                content_summary=analysis_result.caption_suggestion,
                                detected_topics=analysis_result.detected_topics,
                                visual_analysis=analysis_result.to_dict(),
                                sentiment=analysis_result.sentiment,
                                recommended=analysis_result.recommended
                            )
                            session.add(analysis)
                            
                            if analysis_result.recommended:
                                recommended += 1
                                
                        except Exception as e:
                            logger.error(f"AI analysis failed: {e}")
                            # Still save a basic record
                            analysis = VideoAnalysis(
                                content_id=content.content_id,
                                ai_model="error",
                                quality_score=0.5,
                                relevance_score=0.5,
                                visual_analysis={"error": str(e)},
                                recommended=False
                            )
                            session.add(analysis)
                        
                        processed += 1
                        
                        # Commit periodically
                        if processed % 5 == 0:
                            await session.commit()
                            
                    except Exception as e:
                        logger.error(f"Error processing {content.content_id}: {e}")
                        continue
                
                # Final commit
                await session.commit()
                
                # Update job status
                await session.execute(
                    update(Job)
                    .where(Job.job_id == job_id)
                    .values(status="analyzed")
                )
                await session.commit()
                
                logger.info(
                    "Content pool processing complete",
                    job_id=job_id,
                    processed=processed,
                    downloaded=downloaded,
                    analyzed=analyzed,
                    recommended=recommended
                )
                
                # Trigger editing stage if we have recommendations
                if recommended > 0:
                    from app.tasks.editing_tasks import prepare_compilation
                    prepare_compilation.delay(job_id)
                
                return {
                    "status": "success",
                    "job_id": job_id,
                    "processed": processed,
                    "downloaded": downloaded,
                    "analyzed": analyzed,
                    "recommended": recommended
                }
                
            except Exception as e:
                logger.error(f"Content pool processing failed: {e}")
                
                # Update job status
                await session.execute(
                    update(Job)
                    .where(Job.job_id == job_id)
                    .values(
                        status="failed",
                        error_message=str(e)
                    )
                )
                await session.commit()
                raise
    
    return run_async(_process())


@celery_app.task(bind=True, name="analysis.analyze_single_video")
def analyze_single_video(
    self,
    content_id: str,
    video_path: str,
    niche: str
):
    """
    Analyze a single video (for manual/re-analysis).
    
    Args:
        content_id: Content UUID
        video_path: Local path to video file
        niche: Content niche context
    """
    import asyncio
    
    async def _analyze():
        from app.core.analyzer.vision_analyzer import VisionAnalyzer
        from app.models.video_analysis import VideoAnalysis
        from sqlalchemy import select, delete
        
        async with async_session_maker() as session:
            from app.config import settings
            analyzer = VisionAnalyzer(use_free=settings.use_free_analyzer)
            
            # Delete existing analysis
            await session.execute(
                delete(VideoAnalysis)
                .where(VideoAnalysis.content_id == content_id)
            )
            
            # Run analysis
            result = await analyzer.analyze_video(
                video_path=video_path,
                niche_context=niche,
                content_id=content_id
            )
            
            # Save new analysis
            from app.config import settings
            model_name = "free-vision" if settings.use_free_analyzer else "gpt-4-vision"
            analysis = VideoAnalysis(
                content_id=content_id,
                ai_model=model_name,
                quality_score=result.visual_quality_score,
                relevance_score=result.relevance_score,
                virality_score=result.virality_potential,
                content_summary=result.caption_suggestion,
                detected_topics=result.detected_topics,
                visual_analysis=result.to_dict(),
                sentiment=result.sentiment,
                recommended=result.recommended
            )
            session.add(analysis)
            await session.commit()
            
            return result.to_dict()
    
    return run_async(_analyze())


@celery_app.task(name="analysis.reanalyze_batch")
def reanalyze_batch(
    job_id: str,
    new_niche: str,
    limit: int = 20
):
    """
    Re-analyze videos with a new niche context.
    
    Useful when user wants to repurpose content.
    """
    import asyncio
    
    async def _reanalyze():
        from sqlalchemy import select, delete
        from app.core.analyzer.vision_analyzer import VisionAnalyzer
        from app.models.video_analysis import VideoAnalysis
        from app.models.downloaded_video import DownloadedVideo
        from app.models.platform_content import PlatformContent
        
        async with async_session_maker() as session:
            # Get downloaded videos for this job
            result = await session.execute(
                select(DownloadedVideo, PlatformContent)
                .join(PlatformContent)
                .where(PlatformContent.job_id == job_id)
                .limit(limit)
            )
            
            videos = result.all()
            from app.config import settings
            analyzer = VisionAnalyzer(use_free=settings.use_free_analyzer)
            
            updated = 0
            for downloaded, content in videos:
                try:
                    # Delete old analysis
                    await session.execute(
                        delete(VideoAnalysis)
                        .where(VideoAnalysis.content_id == content.content_id)
                    )
                    
                    # Re-analyze
                    analysis_result = await analyzer.analyze_video(
                        video_path=downloaded.local_path,
                        niche_context=new_niche,
                        content_id=str(content.content_id)
                    )
                    
                    # Save
                    model_name = "free-vision" if settings.use_free_analyzer else "gpt-4-vision"
                    analysis = VideoAnalysis(
                        content_id=content.content_id,
                        ai_model=model_name,
                        quality_score=analysis_result.visual_quality_score,
                        relevance_score=analysis_result.relevance_score,
                        content_summary=analysis_result.caption_suggestion,
                        detected_topics=analysis_result.detected_topics,
                        visual_analysis=analysis_result.to_dict(),
                        sentiment=analysis_result.sentiment,
                        recommended=analysis_result.recommended
                    )
                    session.add(analysis)
                    updated += 1
                    
                except Exception as e:
                    logger.error(f"Re-analysis failed: {e}")
            
            await session.commit()
            
            return {
                "status": "success",
                "updated": updated,
                "new_niche": new_niche
            }
    
    return run_async(_reanalyze())


@celery_app.task(name="analysis.quality_check_batch")
def quality_check_batch(video_paths: list):
    """
    Run quality checks on a batch of videos.
    
    Returns list of pass/fail results.
    """
    from app.core.analyzer.quality_checker import BatchQualityChecker
    
    checker = BatchQualityChecker()
    results = checker.check_batch(video_paths)
    
    return {
        path: {
            "passed": report.passed,
            "issues": report.issues,
            "resolution": f"{report.width}x{report.height}",
            "duration": report.duration_seconds
        }
        for path, report in results.items()
    }
