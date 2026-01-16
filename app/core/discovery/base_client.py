"""Abstract base class for all platform discovery clients."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential
import structlog

logger = structlog.get_logger()


@dataclass
class DiscoveredVideo:
    """Standardized video data structure returned by all platform clients."""
    platform: str
    platform_video_id: str
    url: str
    title: str = ""
    description: str = ""
    author: str = ""
    author_id: str = ""
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    duration_seconds: int = 0
    upload_date: datetime = field(default_factory=datetime.now)
    trending_score: float = 0.0
    engagement_rate: float = 0.0
    view_velocity: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            "platform": self.platform,
            "platform_video_id": self.platform_video_id,
            "url": self.url,
            "title": self.title,
            "description": self.description,
            "author": self.author,
            "views": self.views,
            "likes": self.likes,
            "comments": self.comments,
            "duration_seconds": self.duration_seconds,
            "upload_date": self.upload_date,
            "trending_score": self.trending_score,
            "metadata": {
                "author_id": self.author_id,
                "shares": self.shares,
                "engagement_rate": self.engagement_rate,
                "view_velocity": self.view_velocity,
                **self.metadata
            }
        }


class BasePlatformClient(ABC):
    """
    Abstract base class for all platform discovery clients.
    
    Provides:
    - Rate limiting via semaphore
    - Retry logic with exponential backoff
    - Unified viral score calculation
    - Standardized data normalization interface
    """

    def __init__(self, platform_name: str, rate_limit_per_minute: int = 60):
        self.platform_name = platform_name
        self.rate_limit = rate_limit_per_minute
        # Semaphore for rate limiting concurrent requests
        self._semaphore = asyncio.Semaphore(rate_limit_per_minute)
        self._request_count = 0
        self._last_reset = datetime.now()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        """Cleanup resources. Override in subclasses if needed."""
        pass

    @abstractmethod
    async def discover_trending(
        self,
        query: str,
        timeframe_hours: int = 24,
        limit: int = 50
    ) -> List[DiscoveredVideo]:
        """
        Discover trending videos based on query and timeframe.
        
        Args:
            query: Search query or hashtag
            timeframe_hours: How far back to search
            limit: Maximum number of results
            
        Returns:
            List of DiscoveredVideo objects
        """
        pass

    @abstractmethod
    async def get_video_details(self, video_id: str) -> Optional[DiscoveredVideo]:
        """Get detailed information for a specific video."""
        pass

    async def _rate_limited_request(self, coro):
        """
        Execute a coroutine with rate limiting.
        
        Uses semaphore to limit concurrent requests and tracks
        request count for rate limit compliance.
        """
        # Reset counter every minute
        now = datetime.now()
        if (now - self._last_reset).seconds >= 60:
            self._request_count = 0
            self._last_reset = now
        
        # Wait if we've hit the rate limit
        while self._request_count >= self.rate_limit:
            wait_time = 60 - (now - self._last_reset).seconds
            if wait_time > 0:
                logger.debug(
                    f"Rate limit reached for {self.platform_name}, waiting {wait_time}s"
                )
                await asyncio.sleep(wait_time)
            self._request_count = 0
            self._last_reset = datetime.now()
        
        async with self._semaphore:
            self._request_count += 1
            return await coro

    def calculate_viral_score(
        self,
        views: int,
        likes: int,
        comments: int,
        shares: int,
        upload_date: datetime,
        duration_seconds: int = 0
    ) -> tuple[float, float, float]:
        """
        Calculate a normalized 0-100 viral score based on engagement and velocity.
        
        Formula weights:
        - Engagement Rate: 40% (interaction quality)
        - View Velocity: 40% (growth speed)
        - Recency: 20% (freshness bonus)
        
        Returns:
            Tuple of (viral_score, engagement_rate, view_velocity)
        """
        now = datetime.now()
        
        # Handle timezone-aware datetimes
        if upload_date.tzinfo is not None:
            from datetime import timezone
            now = datetime.now(timezone.utc)
        
        time_diff_hours = max(1, (now - upload_date).total_seconds() / 3600)
        
        # 1. Engagement Rate: (Likes + Comments + Shares*2) / Views
        # Shares weighted higher as they indicate strong intent
        total_engagement = likes + comments + (shares * 2)
        engagement_rate = (total_engagement / max(views, 1)) * 100
        
        # 2. View Velocity: Views per hour
        view_velocity = views / time_diff_hours
        
        # 3. Recency Score: Exponential decay over 30 days (720 hours)
        # Newer content gets higher scores
        recency_score = max(0, 1 - (time_diff_hours / 720))
        
        # 4. Duration bonus: Shorts (< 60s) get slight boost
        duration_bonus = 1.0
        if 0 < duration_seconds <= 60:
            duration_bonus = 1.1
        elif duration_seconds > 180:
            duration_bonus = 0.9
        
        # Normalize components (heuristic thresholds based on viral content)
        # - 10% engagement rate is considered exceptional
        # - 5000 views/hour is considered viral velocity
        engagement_component = min(engagement_rate, 20) / 20 * 40
        velocity_component = min(view_velocity, 5000) / 5000 * 40
        recency_component = recency_score * 20
        
        # Calculate final score with duration adjustment
        raw_score = engagement_component + velocity_component + recency_component
        viral_score = round(raw_score * duration_bonus, 2)
        
        # Clamp to 0-100
        viral_score = max(0, min(100, viral_score))
        
        return viral_score, round(engagement_rate, 4), round(view_velocity, 2)

    def _parse_iso_date(self, date_string: str) -> datetime:
        """Parse various ISO date formats."""
        if not date_string:
            return datetime.now()
        
        # Handle various formats
        formats = [
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d"
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_string.replace("+00:00", "Z"), fmt)
            except ValueError:
                continue
        
        # Fallback: try fromisoformat
        try:
            return datetime.fromisoformat(date_string.replace("Z", "+00:00"))
        except ValueError:
            logger.warning(f"Could not parse date: {date_string}")
            return datetime.now()

    def _parse_duration(self, duration_str: str) -> int:
        """Parse ISO 8601 duration (e.g., PT1M30S) to seconds."""
        if not duration_str:
            return 0
        
        import re
        
        # ISO 8601 duration format: PT#H#M#S
        pattern = r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?'
        match = re.match(pattern, duration_str)
        
        if not match:
            return 0
        
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        
        return hours * 3600 + minutes * 60 + seconds
