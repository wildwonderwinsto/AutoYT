"""Intelligent video downloader using yt-dlp."""

import os
import asyncio
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
import hashlib
import structlog

from app.config import settings

logger = structlog.get_logger()


@dataclass
class DownloadResult:
    """Result of a video download operation."""
    success: bool = False
    content_id: str = ""
    local_path: str = ""
    file_size_bytes: int = 0
    duration_seconds: float = 0.0
    resolution: str = ""
    format: str = "mp4"
    fps: int = 0
    error: str = ""
    download_time_seconds: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "content_id": self.content_id,
            "local_path": self.local_path,
            "file_size_bytes": self.file_size_bytes,
            "duration_seconds": self.duration_seconds,
            "resolution": self.resolution,
            "format": self.format,
            "fps": self.fps,
            "error": self.error
        }


class VideoDownloader:
    """
    Intelligent video downloader using yt-dlp.
    
    Handles downloading from:
    - YouTube Shorts
    - TikTok
    - Instagram Reels
    - Snapchat Spotlight
    
    Features:
    - Rate limiting to avoid bans
    - Automatic format selection for quality
    - Resume capability for failed downloads
    - Metadata extraction
    """
    
    # User agents to avoid blocking
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0"
    ]
    
    def __init__(
        self,
        storage_path: str = None,
        max_concurrent: int = None,
        max_file_size_mb: int = None
    ):
        self.storage_path = Path(storage_path or settings.local_storage_path)
        self.raw_dir = self.storage_path / "raw_videos"
        self.temp_dir = self.storage_path / "temp"
        
        # Create directories
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        # Concurrency control
        self.max_concurrent = max_concurrent or settings.max_concurrent_downloads
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        
        # Limits
        self.max_file_size_mb = max_file_size_mb or settings.max_video_size_mb
        
        # Track active downloads
        self._active_downloads: Dict[str, asyncio.Task] = {}
    
    def _get_output_path(self, video_id: str, extension: str = "mp4") -> str:
        """Generate unique output path for a video."""
        # Sanitize video ID for filename
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in video_id)
        filename = f"{safe_id}.{extension}"
        return str(self.raw_dir / filename)
    
    def _get_ydl_options(
        self,
        output_path: str,
        prefer_quality: str = "1080"
    ) -> Dict[str, Any]:
        """Build yt-dlp options for download."""
        import random
        
        # Format selection (prefer MP4, max 1080p for shorts)
        format_str = (
            f"best[ext=mp4][height<={prefer_quality}]/"
            f"best[ext=mp4]/"
            "best[height<=1080]/"
            "best"
        )
        
        return {
            "format": format_str,
            "outtmpl": output_path,
            "quiet": True,
            "no_warnings": True,
            "overwrites": False,
            "noplaylist": True,  # Single video only
            "extract_flat": False,
            
            # Network settings
            "http_headers": {
                "User-Agent": random.choice(self.USER_AGENTS),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
            
            # Performance
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 5,
            
            # File limits
            "max_filesize": self.max_file_size_mb * 1024 * 1024,
            
            # Postprocessing
            "postprocessors": [
                {
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4"
                }
            ],
            
            # Cookie handling for some platforms
            "cookiesfrombrowser": None,  # Set to ("chrome",) if needed
        }
    
    async def download_video(
        self,
        url: str,
        video_id: str,
        content_id: str = ""
    ) -> DownloadResult:
        """
        Download a single video.
        
        Args:
            url: Video URL
            video_id: Platform-specific video ID
            content_id: Internal content ID for tracking
            
        Returns:
            DownloadResult with status and file info
        """
        result = DownloadResult(content_id=content_id or video_id)
        start_time = datetime.now()
        
        output_path = self._get_output_path(video_id)
        
        # Check if already downloaded
        if os.path.exists(output_path):
            logger.info(f"Video already exists: {video_id}")
            result.success = True
            result.local_path = output_path
            result.file_size_bytes = os.path.getsize(output_path)
            return result
        
        async with self._semaphore:
            try:
                import yt_dlp
                
                ydl_opts = self._get_ydl_options(output_path)
                
                # Run download in thread pool
                def _download():
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        return info
                
                info = await asyncio.to_thread(_download)
                
                if info and os.path.exists(output_path):
                    result.success = True
                    result.local_path = output_path
                    result.file_size_bytes = os.path.getsize(output_path)
                    result.duration_seconds = info.get("duration", 0)
                    result.resolution = f"{info.get('width', 0)}x{info.get('height', 0)}"
                    result.fps = int(info.get("fps", 0) or 0)
                    result.format = info.get("ext", "mp4")
                    result.metadata = {
                        "title": info.get("title"),
                        "uploader": info.get("uploader"),
                        "upload_date": info.get("upload_date"),
                        "view_count": info.get("view_count"),
                        "like_count": info.get("like_count")
                    }
                    
                    logger.info(
                        "Download complete",
                        video_id=video_id,
                        size_mb=result.file_size_bytes / (1024 * 1024)
                    )
                else:
                    result.error = "Download completed but file not found"
                    logger.error(result.error, video_id=video_id)
                    
            except Exception as e:
                result.error = str(e)
                logger.error(f"Download failed: {e}", video_id=video_id, url=url)
        
        result.download_time_seconds = (datetime.now() - start_time).total_seconds()
        return result
    
    async def batch_download(
        self,
        videos: List[Dict[str, str]],  # [{"url": ..., "video_id": ..., "content_id": ...}]
        progress_callback=None
    ) -> List[DownloadResult]:
        """
        Download multiple videos with progress tracking.
        
        Args:
            videos: List of video info dicts
            progress_callback: Optional callback(completed, total, result)
            
        Returns:
            List of DownloadResults
        """
        total = len(videos)
        completed = 0
        results = []
        
        async def download_with_callback(video):
            nonlocal completed
            result = await self.download_video(
                url=video["url"],
                video_id=video["video_id"],
                content_id=video.get("content_id", "")
            )
            completed += 1
            
            if progress_callback:
                await progress_callback(completed, total, result)
            
            return result
        
        # Process with limited concurrency
        tasks = [download_with_callback(v) for v in videos]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle exceptions
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                error_result = DownloadResult(
                    content_id=videos[i].get("content_id", ""),
                    error=str(result)
                )
                final_results.append(error_result)
            else:
                final_results.append(result)
        
        return final_results
    
    async def download_for_job(
        self,
        job_id: str,
        limit: int = 30
    ) -> Tuple[List[DownloadResult], int]:
        """
        Download videos associated with a job from the database.
        
        Args:
            job_id: Job UUID
            limit: Maximum videos to download
            
        Returns:
            Tuple of (results, skipped_count)
        """
        from sqlalchemy import select
        from app.core.database import async_session_maker
        from app.models.platform_content import PlatformContent
        from app.models.downloaded_video import DownloadedVideo
        
        async with async_session_maker() as session:
            # Get discovered content for this job
            query = select(PlatformContent).where(
                PlatformContent.job_id == job_id
            ).order_by(
                PlatformContent.trending_score.desc()
            ).limit(limit)
            
            result = await session.execute(query)
            content = result.scalars().all()
            
            # Filter out already downloaded
            videos_to_download = []
            skipped = 0
            
            for c in content:
                # Check if already downloaded
                existing = await session.execute(
                    select(DownloadedVideo).where(
                        DownloadedVideo.content_id == c.content_id
                    )
                )
                
                if existing.scalar_one_or_none():
                    skipped += 1
                    continue
                
                videos_to_download.append({
                    "url": c.url,
                    "video_id": c.platform_video_id,
                    "content_id": str(c.content_id)
                })
            
            logger.info(
                f"Downloading {len(videos_to_download)} videos for job",
                job_id=job_id,
                skipped=skipped
            )
            
            if not videos_to_download:
                return [], skipped
            
            # Download all
            results = await self.batch_download(videos_to_download)
            
            # Save successful downloads to database
            for result in results:
                if result.success:
                    downloaded = DownloadedVideo(
                        content_id=result.content_id,
                        local_path=result.local_path,
                        file_size_bytes=result.file_size_bytes,
                        resolution=result.resolution,
                        format=result.format,
                        fps=result.fps,
                        duration_seconds=result.duration_seconds
                    )
                    session.add(downloaded)
            
            await session.commit()
            
            return results, skipped
    
    def cleanup_temp_files(self, max_age_hours: int = 24):
        """Remove temporary files older than specified age."""
        import time
        
        now = time.time()
        max_age_seconds = max_age_hours * 3600
        
        for file_path in self.temp_dir.iterdir():
            if file_path.is_file():
                age = now - file_path.stat().st_mtime
                if age > max_age_seconds:
                    try:
                        file_path.unlink()
                        logger.debug(f"Deleted temp file: {file_path}")
                    except Exception as e:
                        logger.warning(f"Failed to delete {file_path}: {e}")
    
    def get_download_stats(self) -> Dict[str, Any]:
        """Get download directory statistics."""
        total_size = 0
        file_count = 0
        
        for file_path in self.raw_dir.iterdir():
            if file_path.is_file():
                total_size += file_path.stat().st_size
                file_count += 1
        
        return {
            "total_files": file_count,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "storage_path": str(self.raw_dir)
        }
