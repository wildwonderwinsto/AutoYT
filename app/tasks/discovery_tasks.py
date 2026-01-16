"""Discovery Celery tasks for multi-platform content sourcing."""

from celery import shared_task
from datetime import datetime
import structlog

from workers.celery_app import celery_app
from app.core.database import async_session_maker
from app.models.job import Job, JobStatus
from app.models.platform_content import PlatformContent

logger = structlog.get_logger()


@celery_app.task(bind=True, name="discovery.run_discovery_job")
def run_discovery_job(
    self,
    job_id: str,
    niche: str,
    timeframe_hours: int = 720,
    platforms: list = None,
    per_platform_limit: int = 50
):
    """
    Main discovery task that fetches content from all platforms.
    
    Orchestrates the complete discovery pipeline:
    1. Initialize platform clients
    2. Fetch trending content concurrently
    3. Deduplicate and score
    4. Save to database
    5. Trigger next pipeline stage
    
    Args:
        job_id: UUID of the job to process
        niche: Content niche/category to search
        timeframe_hours: How far back to search (default 30 days)
        platforms: List of platforms to search
        per_platform_limit: Max results per platform
    """
    import asyncio
    
    async def _process():
        from app.core.discovery.orchestrator import DiscoveryOrchestrator
        from sqlalchemy import select, update
        
        async with async_session_maker() as session:
            try:
                # Update job status to discovering
                await session.execute(
                    update(Job)
                    .where(Job.job_id == job_id)
                    .values(status=JobStatus.DISCOVERING)
                )
                await session.commit()
                
                logger.info(
                    "Starting discovery job",
                    job_id=job_id,
                    niche=niche,
                    platforms=platforms
                )
                
                # Initialize orchestrator
                orchestrator = DiscoveryOrchestrator(platforms=platforms)
                
                # Discover content
                videos = await orchestrator.discover_content(
                    query=niche,
                    timeframe_hours=timeframe_hours,
                    per_platform_limit=per_platform_limit,
                    min_viral_score=10.0,  # Minimum quality threshold
                    deduplicate=True
                )
                
                if not videos:
                    logger.warning("No videos found", job_id=job_id, niche=niche)
                    await session.execute(
                        update(Job)
                        .where(Job.job_id == job_id)
                        .values(
                            status=JobStatus.FAILED,
                            error_message="No trending content found for this niche"
                        )
                    )
                    await session.commit()
                    return {"status": "no_content", "job_id": job_id}
                
                # Save discovered content to database
                inserted_count = 0
                duplicate_count = 0
                
                for video in videos:
                    # Check for existing content by URL
                    existing = await session.execute(
                        select(PlatformContent).where(
                            PlatformContent.url == video.url
                        )
                    )
                    
                    if existing.scalar_one_or_none():
                        duplicate_count += 1
                        continue
                    
                    # Create new platform content record
                    video_data = video.to_dict()
                    content = PlatformContent(
                        job_id=job_id,
                        platform=video_data["platform"],
                        platform_video_id=video_data["platform_video_id"],
                        url=video_data["url"],
                        title=video_data["title"],
                        description=video_data.get("description", ""),
                        author=video_data["author"],
                        views=video_data["views"],
                        likes=video_data["likes"],
                        comments=video_data["comments"],
                        duration_seconds=video_data.get("duration_seconds"),
                        upload_date=video_data.get("upload_date"),
                        trending_score=video_data["trending_score"],
                        metadata=video_data.get("metadata", {})
                    )
                    session.add(content)
                    inserted_count += 1
                    
                    # Update progress periodically
                    if inserted_count % 10 == 0:
                        self.update_state(
                            state="PROGRESS",
                            meta={
                                "current": inserted_count,
                                "total": len(videos),
                                "stage": "saving"
                            }
                        )
                
                await session.commit()
                
                # Update job status
                await session.execute(
                    update(Job)
                    .where(Job.job_id == job_id)
                    .values(status="discovered")
                )
                await session.commit()
                
                logger.info(
                    "Discovery job completed",
                    job_id=job_id,
                    inserted=inserted_count,
                    duplicates=duplicate_count,
                    total_found=len(videos)
                )
                
                # Trigger next stage: download
                from app.tasks.download_tasks import batch_download_for_job
                batch_download_for_job.delay(job_id)
                
                return {
                    "status": "success",
                    "job_id": job_id,
                    "inserted": inserted_count,
                    "duplicates": duplicate_count,
                    "total": len(videos)
                }
                
            except Exception as e:
                logger.error(f"Discovery job failed: {e}", job_id=job_id)
                
                # Update job status to failed
                await session.execute(
                    update(Job)
                    .where(Job.job_id == job_id)
                    .values(
                        status=JobStatus.FAILED,
                        error_message=str(e)
                    )
                )
                await session.commit()
                raise
    
    return asyncio.run(_process())


@celery_app.task(bind=True, name="discovery.discover_platform")
def discover_platform(
    self,
    platform: str,
    query: str,
    timeframe_hours: int = 168,
    limit: int = 50
):
    """
    Discover content from a single platform (standalone task).
    
    Can be used for targeted discovery or testing.
    """
    import asyncio
    
    async def _discover():
        if platform == "youtube":
            from app.core.discovery.youtube_client import YouTubeClient
            client = YouTubeClient()
        else:
            from app.core.discovery.social_client import ApifySocialClient
            client = ApifySocialClient(platform)
        
        try:
            videos = await client.discover_trending(query, timeframe_hours, limit)
            
            return {
                "platform": platform,
                "query": query,
                "count": len(videos),
                "top_videos": [
                    {
                        "title": v.title[:50],
                        "views": v.views,
                        "viral_score": v.trending_score,
                        "url": v.url
                    }
                    for v in videos[:5]
                ]
            }
        finally:
            await client.close()
    
    return asyncio.run(_discover())


@celery_app.task(name="discovery.start_discovery_pipeline")
def start_discovery_pipeline(job_id: str):
    """
    Entry point to start the discovery pipeline for a job.
    
    Reads job configuration and triggers the main discovery task.
    """
    import asyncio
    
    async def _start():
        from sqlalchemy import select
        
        async with async_session_maker() as session:
            result = await session.execute(
                select(Job).where(Job.job_id == job_id)
            )
            job = result.scalar_one_or_none()
            
            if not job:
                logger.error("Job not found", job_id=job_id)
                return {"error": "Job not found"}
            
            config = job.config
            
            # Extract configuration
            niche = config.get("niche", "")
            platforms = config.get("platforms", ["youtube", "tiktok"])
            timeframe = config.get("timeframe", "24h")
            max_videos = config.get("max_videos", 100)
            
            # Convert timeframe to hours
            timeframe_map = {
                "1h": 1, "6h": 6, "12h": 12, "24h": 24,
                "7d": 168, "30d": 720
            }
            timeframe_hours = timeframe_map.get(timeframe, 24)
            
            # Calculate per-platform limit
            per_platform_limit = max(max_videos // len(platforms), 25)
            
            logger.info(
                "Starting discovery pipeline",
                job_id=job_id,
                niche=niche,
                platforms=platforms
            )
            
            # Trigger the main discovery task
            run_discovery_job.delay(
                job_id=job_id,
                niche=niche,
                timeframe_hours=timeframe_hours,
                platforms=platforms,
                per_platform_limit=per_platform_limit
            )
            
            return {
                "status": "started",
                "job_id": job_id,
                "niche": niche,
                "platforms": platforms
            }
    
    return asyncio.run(_start())


@celery_app.task(name="discovery.refresh_trending")
def refresh_trending(
    platforms: list = None,
    niches: list = None
):
    """
    Background task to refresh trending content cache.
    
    Run periodically to keep trending data fresh.
    """
    import asyncio
    
    platforms = platforms or ["youtube", "tiktok", "instagram"]
    niches = niches or ["trending"]
    
    async def _refresh():
        from app.core.discovery.orchestrator import DiscoveryOrchestrator
        
        orchestrator = DiscoveryOrchestrator(platforms=platforms)
        results = {}
        
        for niche in niches:
            try:
                videos = await orchestrator.discover_content(
                    query=niche,
                    timeframe_hours=6,  # Last 6 hours only
                    per_platform_limit=25,
                    min_viral_score=20.0
                )
                results[niche] = {
                    "count": len(videos),
                    "top_score": videos[0].trending_score if videos else 0
                }
            except Exception as e:
                logger.error(f"Refresh failed for {niche}: {e}")
                results[niche] = {"error": str(e)}
        
        await orchestrator.close()
        
        logger.info("Trending refresh complete", results=results)
        return results
    
    return asyncio.run(_refresh())


@celery_app.task(name="discovery.analyze_viral_potential")
def analyze_viral_potential(video_urls: list):
    """
    Analyze viral potential of specific video URLs.
    
    Useful for manual video analysis requests.
    """
    import asyncio
    
    async def _analyze():
        from app.core.discovery.youtube_client import YouTubeClient
        from app.utils.validators import extract_platform_from_url, extract_video_id_from_url
        
        results = []
        
        for url in video_urls:
            platform = extract_platform_from_url(url)
            video_id = extract_video_id_from_url(url)
            
            if platform == "youtube" and video_id:
                client = YouTubeClient()
                video = await client.get_video_details(video_id)
                
                if video:
                    results.append({
                        "url": url,
                        "platform": platform,
                        "viral_score": video.trending_score,
                        "engagement_rate": video.engagement_rate,
                        "view_velocity": video.view_velocity,
                        "views": video.views,
                        "recommendation": "high" if video.trending_score > 50 else "medium" if video.trending_score > 25 else "low"
                    })
                else:
                    results.append({"url": url, "error": "Video not found"})
            else:
                results.append({"url": url, "error": f"Unsupported platform: {platform}"})
        
        return results
    
    return asyncio.run(_analyze())
