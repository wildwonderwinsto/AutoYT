"""YouTube Discovery Client using YouTube Data API v3 or free yt-dlp."""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import asyncio
from concurrent.futures import ThreadPoolExecutor
from tenacity import retry, stop_after_attempt, wait_exponential
import structlog

from app.core.discovery.base_client import BasePlatformClient, DiscoveredVideo
from app.config import settings

logger = structlog.get_logger()

# Thread pool for running sync Google API client
_executor = ThreadPoolExecutor(max_workers=10)


class YouTubeClient(BasePlatformClient):
    """
    YouTube Data API v3 client for discovering trending Shorts.
    
    Uses the official Google API client library for reliability and
    proper quota management.
    """
    
    def __init__(self, api_key: str = None, use_api: bool = False):
        super().__init__("youtube", rate_limit_per_minute=100)
        self.api_key = api_key or settings.youtube_api_key
        # Only use API if explicitly enabled AND we have a valid key (not placeholder)
        has_valid_key = bool(self.api_key) and self.api_key not in ["", "your_youtube_key", "YOUR_YOUTUBE_KEY", "your-api-key"]
        self.use_api = use_api and has_valid_key
        self._youtube = None
    
    @property
    def youtube(self):
        """Lazy initialization of YouTube API client."""
        if self._youtube is None:
            try:
                from googleapiclient.discovery import build
                self._youtube = build(
                    "youtube", "v3",
                    developerKey=self.api_key,
                    cache_discovery=False
                )
            except ImportError:
                logger.warning(
                    "google-api-python-client not installed, "
                    "falling back to HTTP client"
                )
                self._youtube = None
        return self._youtube
    
    async def _run_sync(self, func):
        """Run synchronous Google API calls in thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, func)
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def discover_trending(
        self,
        query: str,
        timeframe_hours: int = 24,
        limit: int = 50
    ) -> List[DiscoveredVideo]:
        """
        Discover trending YouTube Shorts for a given query.
        
        Args:
            query: Search term or niche (e.g., "gaming", "cooking tips")
            timeframe_hours: How far back to search for uploads
            limit: Maximum number of results
            
        Returns:
            List of DiscoveredVideo objects sorted by viral score
        """
        logger.info(
            "YouTube discovery starting",
            query=query,
            timeframe_hours=timeframe_hours,
            limit=limit
        )
        
        # Calculate published after date
        published_after = (
            datetime.utcnow() - timedelta(hours=timeframe_hours)
        ).isoformat("T") + "Z"
        
        # Try API first if enabled, fallback to free method
        if self.use_api and self.youtube:
            try:
                result = await self._discover_with_api(query, published_after, limit)
                if result:  # If API returns results, use them
                    return result
                # If API returns empty, fall through to free method
                logger.info("YouTube API returned no results, trying free method")
            except Exception as e:
                logger.warning(f"YouTube API failed, falling back to free method: {e}")
                # Fall through to free method
        
        # Use free HTTP method (yt-dlp based)
        return await self._discover_with_http(query, published_after, limit)
    
    async def _discover_with_api(
        self,
        query: str,
        published_after: str,
        limit: int
    ) -> List[DiscoveredVideo]:
        """Use official Google API client."""
        try:
            # Search for short videos
            def search():
                return self.youtube.search().list(
                    part="id,snippet",
                    q=f"{query} #shorts",
                    type="video",
                    videoDuration="short",  # Under 4 minutes
                    order="viewCount",
                    publishedAfter=published_after,
                    maxResults=min(limit, 50),
                    relevanceLanguage="en",
                    safeSearch="moderate"
                ).execute()
            
            search_response = await self._rate_limited_request(
                self._run_sync(search)
            )
            
            # Extract video IDs
            video_ids = [
                item["id"]["videoId"]
                for item in search_response.get("items", [])
                if item["id"].get("videoId")
            ]
            
            if not video_ids:
                logger.info("No videos found in search results")
                return []
            
            # Fetch detailed statistics for all videos
            return await self._fetch_video_details(video_ids)
            
        except Exception as e:
            logger.error(f"YouTube API search failed: {e}")
            # Don't return empty - let it fall back to free method
            raise  # Re-raise so caller can fallback
    
    async def _fetch_video_details(
        self,
        video_ids: List[str]
    ) -> List[DiscoveredVideo]:
        """Fetch detailed statistics for a batch of videos."""
        if not video_ids:
            return []
        
        try:
            def get_videos():
                return self.youtube.videos().list(
                    part="snippet,statistics,contentDetails",
                    id=",".join(video_ids[:50])  # API limit is 50
                ).execute()
            
            response = await self._rate_limited_request(
                self._run_sync(get_videos)
            )
            
            videos = []
            for item in response.get("items", []):
                video = self._normalize_video(item)
                if video:
                    videos.append(video)
            
            # Sort by viral score
            videos.sort(key=lambda v: v.trending_score, reverse=True)
            
            logger.info(f"YouTube discovery found {len(videos)} videos")
            return videos
            
        except Exception as e:
            logger.error(f"Failed to fetch video details: {e}")
            return []
    
    def _normalize_video(self, item: Dict[str, Any]) -> Optional[DiscoveredVideo]:
        """Convert YouTube API response to DiscoveredVideo."""
        try:
            video_id = item["id"]
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            content = item.get("contentDetails", {})
            
            # Parse dates and duration
            upload_date = self._parse_iso_date(snippet.get("publishedAt", ""))
            duration = self._parse_duration(content.get("duration", ""))
            
            # Skip if longer than 60 seconds (not a Short)
            if duration > 60:
                return None
            
            # Parse statistics
            views = int(stats.get("viewCount", 0))
            likes = int(stats.get("likeCount", 0))
            comments = int(stats.get("commentCount", 0))
            
            # Calculate viral score
            viral_score, engagement_rate, view_velocity = self.calculate_viral_score(
                views=views,
                likes=likes,
                comments=comments,
                shares=0,  # YouTube doesn't expose share count
                upload_date=upload_date,
                duration_seconds=duration
            )
            
            return DiscoveredVideo(
                platform="youtube",
                platform_video_id=video_id,
                url=f"https://www.youtube.com/shorts/{video_id}",
                title=snippet.get("title", ""),
                description=snippet.get("description", "")[:500],
                author=snippet.get("channelTitle", ""),
                author_id=snippet.get("channelId", ""),
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
                    "channel_id": snippet.get("channelId"),
                    "category_id": snippet.get("categoryId"),
                    "tags": snippet.get("tags", [])[:10],
                    "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url")
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to normalize YouTube video: {e}")
            return None
    
    async def _discover_with_http(
        self,
        query: str,
        published_after: str,
        limit: int
    ) -> List[DiscoveredVideo]:
        """
        Free discovery using yt-dlp with YouTube search.
        
        Uses yt-dlp's ytsearch extractor to find videos without API key.
        """
        try:
            import yt_dlp
        except ImportError:
            logger.warning("yt-dlp not available for free YouTube discovery")
            return []
        
        videos = []
        
        try:
            # Use yt-dlp's ytsearch extractor
            search_query = f"{query} shorts"
            
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,  # Need full info for stats
                'skip_download': True,
            }
            
            # Run in thread pool since yt-dlp is synchronous
            def extract_search():
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        # Use ytsearch: prefix for search
                        search_string = f"ytsearch{limit}:{search_query}"
                        logger.debug(f"Searching YouTube with: {search_string}")
                        result = ydl.extract_info(search_string, download=False)
                        logger.debug(f"yt-dlp returned: {type(result)}, entries: {len(result.get('entries', [])) if result else 0}")
                        return result
                except Exception as e:
                    logger.error(f"yt-dlp extraction failed: {e}", exc_info=True)
                    raise
            
            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, extract_search)
            
            if not info:
                logger.warning("yt-dlp search returned no results")
                return []
            
            # Extract entries - ytsearch can return different structures
            entries = []
            if 'entries' in info:
                entries = info['entries']
            elif info and isinstance(info, dict) and 'id' in info:
                # Single result
                entries = [info]
            elif isinstance(info, list):
                entries = info
            
            if not isinstance(entries, list):
                entries = [entries] if entries else []
            
            logger.debug(f"Found {len(entries)} entries from ytsearch")
            
            # Extract video IDs and get full details
            video_ids = []
            for entry in entries:
                if entry and isinstance(entry, dict):
                    vid_id = entry.get('id', '')
                    if vid_id:
                        video_ids.append(vid_id)
            
            if not video_ids:
                logger.warning("No video IDs extracted from search results")
                return []
            
            logger.debug(f"Extracting full details for {len(video_ids)} videos...")
            
            # Get full video details (ytsearch may return limited info)
            for video_id in video_ids[:limit]:
                try:
                    video_url = f"https://www.youtube.com/watch?v={video_id}"
                    
                    # Extract full video info if not already complete
                    def extract_full_info():
                        try:
                            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                return ydl.extract_info(video_url, download=False)
                        except Exception as e:
                            logger.debug(f"Failed to extract full info for {video_id}: {e}")
                            return None
                    
                    full_entry = await loop.run_in_executor(None, extract_full_info)
                    
                    if not full_entry:
                        # Try using the entry from search if available
                        entry = next((e for e in entries if e.get('id') == video_id), None)
                        if not entry:
                            continue
                    else:
                        entry = full_entry
                    
                    # Parse dates
                    upload_date = None
                    if entry.get('upload_date'):
                        try:
                            upload_date = datetime.strptime(
                                entry['upload_date'], 
                                '%Y%m%d'
                            )
                        except:
                            pass
                    elif entry.get('timestamp'):
                        try:
                            upload_date = datetime.fromtimestamp(entry['timestamp'])
                        except:
                            pass
                    
                    # Get statistics - handle None values and missing fields
                    views = int(entry.get('view_count') or entry.get('play_count') or 0)
                    likes = int(entry.get('like_count') or 0)
                    comments = int(entry.get('comment_count') or 0)
                    duration = float(entry.get('duration') or 0)
                    
                    # Calculate viral score
                    viral_score, engagement_rate, view_velocity = self.calculate_viral_score(
                        views=views,
                        likes=likes,
                        comments=comments,
                        shares=0,
                        upload_date=upload_date or datetime.now(),
                        duration_seconds=duration
                    )
                    
                    video = DiscoveredVideo(
                        platform="youtube",
                        platform_video_id=video_id,
                        url=video_url,
                        title=entry.get('title', '')[:200] or '',
                        description=entry.get('description', '')[:500] or '',
                        author=entry.get('uploader', '') or entry.get('channel', '') or '',
                        author_id=entry.get('channel_id', '') or '',
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
                            "channel": entry.get('channel', ''),
                            "tags": entry.get('tags', [])
                        }
                    )
                    videos.append(video)
                except Exception as e:
                    logger.debug(f"Failed to process video entry: {e}")
                    continue
            
            logger.info(f"Free YouTube discovery found {len(videos)} videos for '{query}'")
            return videos
            
        except Exception as e:
            logger.error(f"Free YouTube discovery error: {e}", exc_info=True)
            return []
    
    async def get_video_details(self, video_id: str) -> Optional[DiscoveredVideo]:
        """Get detailed information for a specific YouTube video."""
        videos = await self._fetch_video_details([video_id])
        return videos[0] if videos else None
    
    async def get_channel_shorts(
        self,
        channel_id: str,
        limit: int = 50
    ) -> List[DiscoveredVideo]:
        """Get recent Shorts from a specific channel."""
        try:
            def search_channel():
                return self.youtube.search().list(
                    part="id",
                    channelId=channel_id,
                    type="video",
                    videoDuration="short",
                    order="date",
                    maxResults=min(limit, 50)
                ).execute()
            
            response = await self._rate_limited_request(
                self._run_sync(search_channel)
            )
            
            video_ids = [
                item["id"]["videoId"]
                for item in response.get("items", [])
            ]
            
            return await self._fetch_video_details(video_ids)
            
        except Exception as e:
            logger.error(f"Failed to get channel shorts: {e}")
            return []
