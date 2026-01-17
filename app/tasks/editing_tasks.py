"""Editing Celery tasks for video compilation and rendering."""

from celery import shared_task
import structlog
from datetime import datetime
from typing import List, Dict, Any

from workers.celery_app import celery_app
from app.core.database import async_session_maker
from app.utils.async_utils import run_async

logger = structlog.get_logger()


@celery_app.task(name="editing.prepare_compilation")
def prepare_compilation(job_id: str):
    """
    Prepare for compilation after analysis is complete.
    
    Validates content availability and triggers rendering.
    """
    import asyncio
    
    async def _prepare():
        from sqlalchemy import select, func
        from app.models.job import Job, JobStatus
        from app.models.platform_content import PlatformContent
        from app.models.video_analysis import VideoAnalysis
        
        async with async_session_maker() as session:
            # Count recommended videos
            result = await session.execute(
                select(func.count(VideoAnalysis.analysis_id))
                .join(PlatformContent)
                .where(
                    PlatformContent.job_id == job_id,
                    VideoAnalysis.recommended == True
                )
            )
            recommended_count = result.scalar() or 0
            
            if recommended_count < 3:
                logger.warning(
                    "Not enough recommended videos",
                    job_id=job_id,
                    count=recommended_count
                )
                return {
                    "status": "insufficient_content",
                    "recommended_count": recommended_count,
                    "minimum_required": 3
                }
            
            # Get job settings
            job_result = await session.execute(
                select(Job).where(Job.job_id == job_id)
            )
            job = job_result.scalar_one_or_none()
            
            if job and job.config.get("auto_compile", True):
                top_n = min(recommended_count, job.config.get("top_n", 10))
                render_final_video.delay(job_id, top_n)
                
                return {
                    "status": "compilation_started",
                    "job_id": job_id,
                    "clip_count": top_n
                }
            
            return {
                "status": "ready_for_manual_compilation",
                "job_id": job_id,
                "recommended_count": recommended_count
            }
    
    return run_async(_prepare())


@celery_app.task(bind=True, name="editing.render_final_video", queue="video_processing")
def render_final_video(
    self,
    job_id: str,
    top_n: int = 10,
    render_settings: Dict[str, Any] = None
):
    """
    Complete rendering pipeline with TTS and video composition.
    
    1. Fetch selected clips from database
    2. Generate TTS voiceovers
    3. Mix audio with background music
    4. Composite video with overlays
    5. Export final file
    """
    import asyncio
    
    async def _render():
        from sqlalchemy import select, desc, update
        from app.core.audio.tts_service import TTSService, VoiceStyle
        from app.core.audio.audio_mixer import AudioMixer
        from app.core.editor.compositor import VideoCompositor, ClipConfig, CompositorConfig
        from app.models.job import Job, JobStatus
        from app.models.platform_content import PlatformContent
        from app.models.video_analysis import VideoAnalysis
        from app.models.downloaded_video import DownloadedVideo
        from app.models.output_video import OutputVideo
        from app.config import settings as app_settings
        
        render_settings = render_settings or {}
        
        async with async_session_maker() as session:
            try:
                # Update job status
                await session.execute(
                    update(Job)
                    .where(Job.job_id == job_id)
                    .values(status=JobStatus.EDITING)
                )
                await session.commit()
                
                # Get job config
                job_result = await session.execute(
                    select(Job).where(Job.job_id == job_id)
                )
                job = job_result.scalar_one_or_none()
                
                if not job:
                    return {"error": "Job not found"}
                
                config = job.config
                niche = config.get("niche", "content")
                
                # Fetch top recommended videos
                result = await session.execute(
                    select(PlatformContent, VideoAnalysis, DownloadedVideo)
                    .join(VideoAnalysis, PlatformContent.content_id == VideoAnalysis.content_id)
                    .join(DownloadedVideo, PlatformContent.content_id == DownloadedVideo.content_id)
                    .where(
                        PlatformContent.job_id == job_id,
                        VideoAnalysis.recommended == True
                    )
                    .order_by(
                        desc(
                            VideoAnalysis.quality_score * 0.3 +
                            VideoAnalysis.virality_score * 0.4 +
                            VideoAnalysis.relevance_score * 0.3
                        )
                    )
                    .limit(top_n)
                )
                
                rows = result.all()
                
                if not rows:
                    await session.execute(
                        update(Job)
                        .where(Job.job_id == job_id)
                        .values(status=JobStatus.FAILED, error_message="No recommended videos found")
                    )
                    await session.commit()
                    return {"error": "No recommended videos"}
                
                logger.info(
                    "Starting render pipeline",
                    job_id=job_id,
                    clips=len(rows)
                )
                
                self.update_state(
                    state="PROGRESS",
                    meta={"stage": "generating_tts", "progress": 10}
                )
                
                # Step 1: Generate TTS
                voice_style = VoiceStyle.ENERGETIC
                if render_settings.get("voice_style") == "calm":
                    voice_style = VoiceStyle.CALM
                elif render_settings.get("voice_style") == "dramatic":
                    voice_style = VoiceStyle.DRAMATIC
                
                tts = TTSService(voice_style=voice_style)
                
                clips_data = []
                for content, analysis, download in rows:
                    clips_data.append({
                        "content_id": str(content.content_id),
                        "local_path": download.local_path,
                        "title": content.title,
                        "caption_suggestion": (
                            analysis.visual_analysis.get("caption_suggestion", "")
                            if analysis.visual_analysis else content.title
                        ),
                        "duration": download.duration_seconds or 10.0
                    })
                
                # Reverse for countdown (10 to 1)
                clips_data.reverse()
                
                # Generate TTS for all clips
                tts_results = tts.generate_ranking_audio_set(niche, clips_data)
                
                self.update_state(
                    state="PROGRESS",
                    meta={"stage": "mixing_audio", "progress": 30}
                )
                
                # Step 2: Mix audio
                mixer = AudioMixer()
                
                # Get background music path
                bg_music_path = render_settings.get("bg_music_path")
                if not bg_music_path:
                    # Use default
                    bg_music_path = str(
                        Path(app_settings.local_storage_path) / 
                        "assets" / "background_music.mp3"
                    )
                
                clip_durations = [c["duration"] for c in clips_data]
                
                if Path(bg_music_path).exists():
                    audio_result = mixer.create_ranking_audio(
                        bg_music_path=bg_music_path,
                        tts_results=tts_results,
                        clip_durations=clip_durations
                    )
                    audio_track = audio_result.output_path if audio_result.success else None
                else:
                    audio_track = None
                    logger.warning("No background music found")
                
                self.update_state(
                    state="PROGRESS",
                    meta={"stage": "compositing_video", "progress": 50}
                )
                
                # Step 3: Prepare clip configs
                clip_configs = []
                for i, clip_data in enumerate(clips_data):
                    rank = len(clips_data) - i  # Countdown
                    
                    clip_config = ClipConfig(
                        path=clip_data["local_path"],
                        rank=rank,
                        caption=clip_data["caption_suggestion"][:80],
                        duration=min(clip_data["duration"], 12.0),
                        volume=0.1
                    )
                    clip_configs.append(clip_config)
                
                # Step 4: Render video
                compositor_config = CompositorConfig()
                
                # Apply render settings
                if render_settings.get("font_color"):
                    compositor_config.rank_style.color = render_settings["font_color"]
                if render_settings.get("font_size"):
                    compositor_config.caption_style.size = render_settings["font_size"]
                
                compositor = VideoCompositor(compositor_config)
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_filename = f"ranking_{niche}_{timestamp}.mp4"
                
                self.update_state(
                    state="PROGRESS",
                    meta={"stage": "rendering", "progress": 70}
                )
                
                render_result = compositor.render_ranking_video(
                    clips=clip_configs,
                    output_filename=output_filename,
                    title=f"Top {len(clip_configs)} {niche.title()}",
                    audio_track=audio_track
                )
                
                if not render_result.success:
                    await session.execute(
                        update(Job)
                        .where(Job.job_id == job_id)
                        .values(status=JobStatus.FAILED, error_message=render_result.error)
                    )
                    await session.commit()
                    return {"error": render_result.error}
                
                self.update_state(
                    state="PROGRESS",
                    meta={"stage": "saving", "progress": 95}
                )
                
                # Step 5: Save output record
                ranking_items = [
                    {
                        "rank": len(clips_data) - i,
                        "content_id": c["content_id"],
                        "title": c["title"]
                    }
                    for i, c in enumerate(clips_data)
                ]
                
                output_video = OutputVideo(
                    job_id=job_id,
                    title=f"Top {len(clips_data)} {niche.title()} Videos",
                    description=f"AI-curated ranking of the best {niche} content",
                    tags=[niche, "ranking", "compilation", "shorts", "trending"],
                    ranking_items=ranking_items,
                    local_path=render_result.output_path,
                    duration_seconds=render_result.duration_seconds,
                    resolution=render_result.resolution,
                    file_size_bytes=render_result.file_size_bytes,
                    render_settings=render_settings
                )
                session.add(output_video)
                
                # Update job status
                await session.execute(
                    update(Job)
                    .where(Job.job_id == job_id)
                    .values(status=JobStatus.COMPLETED, completed_at=datetime.utcnow())
                )
                await session.commit()
                
                # Cleanup TTS temp files
                tts.cleanup_temp_files()
                
                logger.info(
                    "Render complete",
                    job_id=job_id,
                    output=render_result.output_path,
                    duration=render_result.duration_seconds
                )
                
                return {
                    "status": "success",
                    "job_id": job_id,
                    "output_id": str(output_video.output_id),
                    "output_path": render_result.output_path,
                    "duration_seconds": render_result.duration_seconds,
                    "file_size_mb": render_result.file_size_bytes / (1024 * 1024)
                }
                
            except Exception as e:
                logger.error(f"Render failed: {e}", job_id=job_id)
                
                await session.execute(
                    update(Job)
                    .where(Job.job_id == job_id)
                    .values(status=JobStatus.FAILED, error_message=str(e))
                )
                await session.commit()
                raise
    
    from pathlib import Path
    return run_async(_render())


@celery_app.task(bind=True, name="editing.render_custom_video", queue="video_processing")
def render_custom_video(
    self,
    job_id: str,
    content_ids: List[str],
    captions: Dict[str, str] = None,
    render_settings: Dict[str, Any] = None
):
    """
    Render a custom video with user-selected clips and captions.
    
    Allows manual ordering and caption overrides.
    """
    import asyncio
    
    async def _render():
        from sqlalchemy import select
        from app.core.editor.compositor import VideoCompositor, ClipConfig, CompositorConfig
        from app.models.platform_content import PlatformContent
        from app.models.downloaded_video import DownloadedVideo
        from app.models.output_video import OutputVideo
        
        captions = captions or {}
        render_settings = render_settings or {}
        
        async with async_session_maker() as session:
            # Fetch specified content in order
            clip_configs = []
            
            for i, content_id in enumerate(content_ids):
                result = await session.execute(
                    select(PlatformContent, DownloadedVideo)
                    .join(DownloadedVideo, PlatformContent.content_id == DownloadedVideo.content_id)
                    .where(PlatformContent.content_id == content_id)
                )
                row = result.first()
                
                if not row:
                    continue
                
                content, download = row
                
                rank = len(content_ids) - i
                caption = captions.get(content_id, content.title[:80])
                
                clip_configs.append(ClipConfig(
                    path=download.local_path,
                    rank=rank,
                    caption=caption,
                    duration=min(download.duration_seconds or 10.0, 12.0)
                ))
            
            if not clip_configs:
                return {"error": "No valid clips found"}
            
            # Render
            compositor = VideoCompositor()
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            result = compositor.render_ranking_video(
                clips=clip_configs,
                output_filename=f"custom_{timestamp}.mp4"
            )
            
            if not result.success:
                return {"error": result.error}
            
            # Save output
            output_video = OutputVideo(
                job_id=job_id,
                title="Custom Compilation",
                ranking_items=[
                    {"rank": len(content_ids) - i, "content_id": cid}
                    for i, cid in enumerate(content_ids)
                ],
                local_path=result.output_path,
                duration_seconds=result.duration_seconds,
                resolution=result.resolution,
                file_size_bytes=result.file_size_bytes,
                render_settings=render_settings
            )
            session.add(output_video)
            await session.commit()
            
            return {
                "status": "success",
                "output_id": str(output_video.output_id),
                "output_path": result.output_path
            }
    
    return run_async(_render())


@celery_app.task(name="editing.generate_preview")
def generate_preview(job_id: str):
    """Generate a preview thumbnail for a job."""
    import asyncio
    
    async def _preview():
        from sqlalchemy import select, desc
        from app.core.editor.compositor import VideoCompositor
        from app.models.platform_content import PlatformContent
        from app.models.video_analysis import VideoAnalysis
        from app.models.downloaded_video import DownloadedVideo
        
        async with async_session_maker() as session:
            # Get top clip
            result = await session.execute(
                select(DownloadedVideo)
                .join(PlatformContent)
                .join(VideoAnalysis)
                .where(
                    PlatformContent.job_id == job_id,
                    VideoAnalysis.recommended == True
                )
                .order_by(desc(VideoAnalysis.quality_score))
                .limit(1)
            )
            
            download = result.scalar_one_or_none()
            
            if not download:
                return {"error": "No clips available"}
            
            compositor = VideoCompositor()
            from app.core.editor.compositor import ClipConfig
            
            preview_path = compositor.get_render_preview(
                [ClipConfig(path=download.local_path)],
                frame_time=2.0
            )
            
            return {"preview_path": preview_path}
    
    return run_async(_preview())
