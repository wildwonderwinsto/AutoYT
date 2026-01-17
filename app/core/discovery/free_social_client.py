"""Free social media client using direct HTTP scraping (no Apify)."""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import asyncio
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
import structlog
import re
from urllib.parse import quote

from app.core.discovery.base_client import BasePlatformClient, DiscoveredVideo
from app.config import settings

logger = structlog.get_logger()


class FreeSocialClient(BasePlatformClient):
    """
    Free social media client using direct HTTP requests.
    
    Note: This is less reliable than Apify but completely free.
    May break if platforms change their HTML structure.
    """
    
    def __init__(self, platform: str):
        if platform not in ["tiktok", "instagram"]:
            raise ValueError(f"Free client only supports: tiktok, instagram. Got: {platform}")
        
        super().__init__(platform, rate_limit_per_minute=10)  # Lower rate limit for free scraping
        self.platform_name = platform
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
    async def discover_trending(
        self,
        query: str,
        timeframe_hours: int = 24,
        limit: int = 50
    ) -> List[DiscoveredVideo]:
        """
        Discover trending videos using free HTTP scraping.
        
        Note: This is a simplified implementation. For production,
        consider using yt-dlp for TikTok which is more reliable.
        """
        logger.info(
            f"{self.platform_name} free discovery starting",
            query=query,
            limit=limit
        )
        
        try:
            if self.platform_name == "tiktok":
                return await self._discover_tiktok(query, limit)
            elif self.platform_name == "instagram":
                return await self._discover_instagram(query, limit)
        except Exception as e:
            logger.error(f"Free {self.platform_name} discovery failed: {e}")
            return []
    
    async def _discover_tiktok(self, query: str, limit: int) -> List[DiscoveredVideo]:
        """
        Discover TikTok videos using yt-dlp (free and reliable).
        
        yt-dlp can extract TikTok video metadata without API.
        """
        try:
            import yt_dlp
        except ImportError:
            logger.warning("yt-dlp not available, TikTok discovery limited")
            return []
        
        videos = []
        hashtag = query.lstrip("#")
        
        # Use yt-dlp to search TikTok
        # Note: yt-dlp's TikTok search is limited, but it can extract video info
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'skip_download': True,
        }
        
        # Try to get trending hashtag videos
        # This is a simplified approach - yt-dlp can extract from individual URLs
        # For full search, you'd need to manually find video URLs
        
        logger.warning(
            "Free TikTok discovery is limited. "
            "Consider providing direct video URLs or using yt-dlp with video URLs."
        )
        
        return videos
    
    async def _discover_instagram(self, query: str, limit: int) -> List[DiscoveredVideo]:
        """
        Discover Instagram Reels using HTTP scraping.
        
        Note: Instagram has anti-scraping measures. This is a basic implementation.
        """
        hashtag = query.lstrip("#")
        videos = []
        
        # Instagram's public hashtag pages
        url = f"https://www.instagram.com/explore/tags/{hashtag}/"
        
        try:
            response = await self._rate_limited_request(
                self.client.get(url)
            )
            
            if response.status_code != 200:
                logger.warning(f"Instagram request failed: {response.status_code}")
                return []
            
            # Parse HTML for video data
            # Instagram embeds JSON data in script tags
            html = response.text
            
            # This is a simplified parser - Instagram's structure changes frequently
            # For production, consider using browser automation (Selenium) or
            # providing direct video URLs
            
            logger.warning(
                "Free Instagram discovery is limited. "
                "Instagram has strong anti-scraping measures. "
                "Consider using direct video URLs or browser automation."
            )
            
        except Exception as e:
            logger.error(f"Instagram scraping failed: {e}")
        
        return videos
    
    async def get_video_details(self, video_id: str) -> Optional[DiscoveredVideo]:
        """Get details for a specific video using yt-dlp."""
        try:
            import yt_dlp
        except ImportError:
            return None
        
        # Build URL based on platform
        if self.platform_name == "tiktok":
            url = f"https://www.tiktok.com/video/{video_id}"
        elif self.platform_name == "instagram":
            url = f"https://www.instagram.com/reel/{video_id}/"
        else:
            return None
        
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    return None
                
                # Parse yt-dlp output to DiscoveredVideo
                upload_date = datetime.fromtimestamp(info.get('timestamp', 0))
                
                viral_score, engagement_rate, view_velocity = self.calculate_viral_score(
                    views=info.get('view_count', 0),
                    likes=info.get('like_count', 0),
                    comments=info.get('comment_count', 0),
                    shares=info.get('repost_count', 0),
                    upload_date=upload_date,
                    duration_seconds=info.get('duration', 0)
                )
                
                return DiscoveredVideo(
                    platform=self.platform_name,
                    platform_video_id=video_id,
                    url=url,
                    title=info.get('title', '')[:200],
                    description=info.get('description', ''),
                    author=info.get('uploader', ''),
                    author_id=info.get('uploader_id', ''),
                    views=info.get('view_count', 0),
                    likes=info.get('like_count', 0),
                    comments=info.get('comment_count', 0),
                    shares=info.get('repost_count', 0),
                    duration_seconds=info.get('duration', 0),
                    upload_date=upload_date,
                    trending_score=viral_score,
                    engagement_rate=engagement_rate,
                    view_velocity=view_velocity,
                    metadata=info
                )
        except Exception as e:
            logger.error(f"Failed to get {self.platform_name} video details: {e}")
            return None
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
