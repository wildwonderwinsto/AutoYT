"""Multi-platform social media client using Apify actors."""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import asyncio
from concurrent.futures import ThreadPoolExecutor
from tenacity import retry, stop_after_attempt, wait_exponential
import structlog

from app.core.discovery.base_client import BasePlatformClient, DiscoveredVideo
from app.config import settings

logger = structlog.get_logger()

# Thread pool for Apify sync client
_executor = ThreadPoolExecutor(max_workers=5)


class ApifySocialClient(BasePlatformClient):
    """
    Multi-platform client for TikTok, Instagram, and Snapchat.
    
    Uses Apify actors (pre-built scrapers) for reliable data collection
    without maintaining custom scrapers.
    """
    
    # Mapping of platform names to Apify actor IDs
    ACTOR_MAPPING = {
        "tiktok": "clockworks/free-tiktok-scraper",
        "instagram": "apify/instagram-scraper",
        "snapchat": "apify/snapchat-scraper"
    }
    
    # Platform-specific configurations
    PLATFORM_CONFIG = {
        "tiktok": {
            "search_field": "hashtags",
            "limit_field": "resultsPerPage",
            "video_filter": lambda x: x.get("videoMeta") is not None
        },
        "instagram": {
            "search_field": "hashtags",
            "limit_field": "resultsLimit",
            "video_filter": lambda x: x.get("type") == "Video"
        },
        "snapchat": {
            "search_field": "hashtags",
            "limit_field": "maxResults",
            "video_filter": lambda x: True
        }
    }
    
    def __init__(self, platform: str, apify_api_key: str = None, use_free: bool = True):
        if platform not in self.ACTOR_MAPPING:
            raise ValueError(f"Unsupported platform: {platform}. Choose from: {list(self.ACTOR_MAPPING.keys())}")
        
        super().__init__(platform, rate_limit_per_minute=20)
        self.apify_api_key = apify_api_key or settings.apify_api_key
        # Force free mode if no valid API key or if explicitly requested
        has_valid_key = bool(self.apify_api_key) and self.apify_api_key not in ["", "your_apify_key", "apify_..."]
        self.use_free = use_free or not has_valid_key
        self.actor_id = self.ACTOR_MAPPING[platform]
        self.config = self.PLATFORM_CONFIG[platform]
        self._client = None
        self._free_client = None
    
    @property
    def client(self):
        """Lazy initialization of Apify client."""
        if self._client is None:
            try:
                from apify_client import ApifyClient
                self._client = ApifyClient(self.apify_api_key)
            except ImportError:
                logger.error("apify-client not installed")
                raise ImportError("Please install apify-client: pip install apify-client")
        return self._client
    
    async def _run_sync(self, func):
        """Run synchronous Apify client calls in thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, func)
    
    @property
    def free_client(self):
        """Lazy initialization of free client."""
        if self._free_client is None and self.use_free:
            from app.core.discovery.free_social_client import FreeSocialClient
            self._free_client = FreeSocialClient(self.platform_name)
        return self._free_client
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
    async def discover_trending(
        self,
        query: str,
        timeframe_hours: int = 24,
        limit: int = 50
    ) -> List[DiscoveredVideo]:
        """
        Discover trending videos from TikTok, Instagram, or Snapchat.
        
        Uses free client if no Apify API key, otherwise uses Apify.
        
        Args:
            query: Hashtag or search query
            timeframe_hours: Not directly filterable, used for scoring
            limit: Maximum number of results
            
        Returns:
            List of DiscoveredVideo objects
        """
        # Use free client if enabled
        if self.use_free:
            return await self.free_client.discover_trending(query, timeframe_hours, limit)
        
        logger.info(
            f"{self.platform_name} discovery starting (Apify)",
            query=query,
            limit=limit
        )
        
        # Prepare hashtag format
        hashtag = query.lstrip("#")
        
        # Build actor input based on platform
        run_input = self._build_actor_input(hashtag, limit)
        
        try:
            # Run the actor
            def run_actor():
                return self.client.actor(self.actor_id).call(
                    run_input=run_input,
                    timeout_secs=300  # 5 minute timeout
                )
            
            run = await self._rate_limited_request(
                self._run_sync(run_actor)
            )
            
            if not run or run.get("status") not in ["SUCCEEDED", "RUNNING"]:
                logger.error(f"Apify actor failed: {run}")
                return []
            
            # Fetch results from dataset
            def get_items():
                return list(self.client.dataset(run["defaultDatasetId"]).iterate_items())
            
            items = await self._run_sync(get_items)
            
            # Filter and normalize
            videos = []
            video_filter = self.config["video_filter"]
            
            for item in items:
                if not video_filter(item):
                    continue
                
                video = self._normalize_item(item)
                if video:
                    videos.append(video)
            
            # Sort by viral score
            videos.sort(key=lambda v: v.trending_score, reverse=True)
            
            # Filter by recency if timeframe specified
            if timeframe_hours:
                cutoff = datetime.now() - timedelta(hours=timeframe_hours)
                videos = [v for v in videos if v.upload_date >= cutoff]
            
            logger.info(f"{self.platform_name} discovery found {len(videos)} videos")
            return videos[:limit]
            
        except Exception as e:
            logger.error(f"Apify discovery failed for {self.platform_name}: {e}")
            # Fallback to free client on error
            if self.free_client:
                logger.info(f"Falling back to free {self.platform_name} client")
                return await self.free_client.discover_trending(query, timeframe_hours, limit)
            return []
    
    def _build_actor_input(self, hashtag: str, limit: int) -> Dict[str, Any]:
        """Build platform-specific actor input configuration."""
        search_field = self.config["search_field"]
        limit_field = self.config["limit_field"]
        
        base_input = {
            search_field: [hashtag],
            limit_field: limit,
        }
        
        # Platform-specific additions
        if self.platform_name == "tiktok":
            base_input.update({
                "shouldDownloadVideos": False,
                "shouldDownloadCovers": False,
                "shouldDownloadSlideshowImages": False
            })
        elif self.platform_name == "instagram":
            base_input.update({
                "resultsType": "posts",
                "searchType": "hashtag"
            })
        
        return base_input
    
    def _normalize_item(self, raw: Dict[str, Any]) -> Optional[DiscoveredVideo]:
        """Normalize platform-specific data to DiscoveredVideo."""
        try:
            if self.platform_name == "tiktok":
                return self._normalize_tiktok(raw)
            elif self.platform_name == "instagram":
                return self._normalize_instagram(raw)
            elif self.platform_name == "snapchat":
                return self._normalize_snapchat(raw)
            return None
        except Exception as e:
            logger.debug(f"Failed to normalize {self.platform_name} item: {e}")
            return None
    
    def _normalize_tiktok(self, raw: Dict[str, Any]) -> Optional[DiscoveredVideo]:
        """Normalize TikTok data."""
        video_meta = raw.get("videoMeta", {})
        author_meta = raw.get("authorMeta", {})
        
        # Parse upload date
        create_time = raw.get("createTime", 0)
        if isinstance(create_time, (int, float)):
            upload_date = datetime.fromtimestamp(create_time)
        else:
            upload_date = self._parse_iso_date(str(create_time))
        
        # Statistics
        views = int(raw.get("playCount", 0))
        likes = int(raw.get("diggCount", 0))
        comments = int(raw.get("commentCount", 0))
        shares = int(raw.get("shareCount", 0))
        duration = int(video_meta.get("duration", 0))
        
        # Calculate viral score
        viral_score, engagement_rate, view_velocity = self.calculate_viral_score(
            views=views,
            likes=likes,
            comments=comments,
            shares=shares,
            upload_date=upload_date,
            duration_seconds=duration
        )
        
        return DiscoveredVideo(
            platform="tiktok",
            platform_video_id=raw.get("id", ""),
            url=raw.get("webVideoUrl", "") or raw.get("url", ""),
            title=raw.get("text", "")[:200],
            description=raw.get("text", ""),
            author=author_meta.get("name", "") or author_meta.get("nickName", ""),
            author_id=author_meta.get("id", ""),
            views=views,
            likes=likes,
            comments=comments,
            shares=shares,
            duration_seconds=duration,
            upload_date=upload_date,
            trending_score=viral_score,
            engagement_rate=engagement_rate,
            view_velocity=view_velocity,
            metadata={
                "music": raw.get("musicMeta", {}),
                "hashtags": [h.get("name") for h in raw.get("hashtags", [])],
                "cover_url": video_meta.get("cover")
            }
        )
    
    def _normalize_instagram(self, raw: Dict[str, Any]) -> Optional[DiscoveredVideo]:
        """Normalize Instagram Reels data."""
        # Parse upload date
        timestamp = raw.get("timestamp") or raw.get("taken_at_timestamp")
        if isinstance(timestamp, (int, float)):
            upload_date = datetime.fromtimestamp(timestamp)
        else:
            upload_date = self._parse_iso_date(str(timestamp or ""))
        
        # Statistics
        views = int(raw.get("videoPlayCount", 0) or raw.get("video_view_count", 0))
        likes = int(raw.get("likesCount", 0) or raw.get("edge_liked_by", {}).get("count", 0))
        comments = int(raw.get("commentsCount", 0) or raw.get("edge_media_to_comment", {}).get("count", 0))
        duration = int(raw.get("videoDuration", 0) or raw.get("video_duration", 0))
        
        # Calculate viral score
        viral_score, engagement_rate, view_velocity = self.calculate_viral_score(
            views=views,
            likes=likes,
            comments=comments,
            shares=0,
            upload_date=upload_date,
            duration_seconds=duration
        )
        
        # Build URL
        shortcode = raw.get("shortCode") or raw.get("shortcode", "")
        url = raw.get("url") or f"https://www.instagram.com/reel/{shortcode}/"
        
        return DiscoveredVideo(
            platform="instagram",
            platform_video_id=raw.get("id", shortcode),
            url=url,
            title=raw.get("caption", "")[:200] if raw.get("caption") else "",
            description=raw.get("caption", ""),
            author=raw.get("ownerUsername", "") or raw.get("owner", {}).get("username", ""),
            author_id=raw.get("ownerId", "") or raw.get("owner", {}).get("id", ""),
            views=views,
            likes=likes,
            comments=comments,
            shares=0,
            duration_seconds=duration,
            upload_date=upload_date,
            trending_score=viral_score,
            engagement_rate=engagement_rate,
            view_velocity=view_velocity,
            metadata={
                "hashtags": raw.get("hashtags", []),
                "mentions": raw.get("mentions", []),
                "thumbnail": raw.get("displayUrl")
            }
        )
    
    def _normalize_snapchat(self, raw: Dict[str, Any]) -> Optional[DiscoveredVideo]:
        """Normalize Snapchat Spotlight data."""
        # Snapchat data structure varies, this is a generic handler
        upload_date = self._parse_iso_date(raw.get("timestamp", ""))
        
        views = int(raw.get("viewCount", 0))
        likes = int(raw.get("likeCount", 0))
        
        viral_score, engagement_rate, view_velocity = self.calculate_viral_score(
            views=views,
            likes=likes,
            comments=0,
            shares=0,
            upload_date=upload_date
        )
        
        return DiscoveredVideo(
            platform="snapchat",
            platform_video_id=raw.get("id", ""),
            url=raw.get("url", ""),
            title=raw.get("title", ""),
            description=raw.get("description", ""),
            author=raw.get("username", ""),
            author_id=raw.get("userId", ""),
            views=views,
            likes=likes,
            comments=0,
            shares=0,
            duration_seconds=int(raw.get("duration", 0)),
            upload_date=upload_date,
            trending_score=viral_score,
            engagement_rate=engagement_rate,
            view_velocity=view_velocity,
            metadata=raw.get("metadata", {})
        )
    
    async def get_video_details(self, video_id: str) -> Optional[DiscoveredVideo]:
        """Get details for a specific video. Limited support for social platforms."""
        logger.warning(
            f"Individual video lookup not fully supported for {self.platform_name}"
        )
        return None
