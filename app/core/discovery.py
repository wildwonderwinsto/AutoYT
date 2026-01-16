"""Platform discovery engines for trending content"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
import structlog

from app.config import settings

logger = structlog.get_logger()


@dataclass
class DiscoveredContent:
    """Represents discovered content from a platform"""
    platform: str
    platform_video_id: str
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    views: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    duration_seconds: Optional[int] = None
    upload_date: Optional[datetime] = None
    trending_score: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None


class BaseDiscovery(ABC):
    """Base class for platform discovery engines"""
    
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    @abstractmethod
    async def discover_trending(
        self,
        niche: str,
        limit: int = 100,
        timeframe: str = "24h"
    ) -> List[DiscoveredContent]:
        """Discover trending content for a niche"""
        pass
    
    @abstractmethod
    async def get_video_details(self, video_id: str) -> Optional[DiscoveredContent]:
        """Get detailed information for a specific video"""
        pass
    
    def calculate_trending_score(
        self,
        views: int,
        likes: int,
        comments: int,
        age_hours: float
    ) -> float:
        """Calculate a normalized trending score"""
        if age_hours <= 0:
            age_hours = 1
        
        # Engagement rate with time decay
        engagement = (likes + comments * 2) / max(views, 1)
        velocity = views / age_hours
        
        # Normalize score to 0-1 range
        score = min(1.0, (engagement * 0.4) + (velocity / 10000 * 0.6))
        return round(score, 4)


class YouTubeDiscovery(BaseDiscovery):
    """YouTube trending content discovery"""
    
    def __init__(self):
        super().__init__()
        self.api_key = settings.youtube_api_key
        self.base_url = "https://www.googleapis.com/youtube/v3"
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def discover_trending(
        self,
        niche: str,
        limit: int = 100,
        timeframe: str = "24h"
    ) -> List[DiscoveredContent]:
        """Discover trending YouTube Shorts for a niche"""
        logger.info("Discovering YouTube trends", niche=niche, limit=limit)
        
        results = []
        
        # Search for trending shorts in niche
        params = {
            "part": "snippet,statistics",
            "q": f"{niche} #shorts",
            "type": "video",
            "videoDuration": "short",
            "order": "viewCount",
            "maxResults": min(limit, 50),
            "key": self.api_key
        }
        
        try:
            response = await self.client.get(
                f"{self.base_url}/search",
                params=params
            )
            response.raise_for_status()
            data = response.json()
            
            video_ids = [item["id"]["videoId"] for item in data.get("items", [])]
            
            # Get detailed statistics for each video
            if video_ids:
                stats_response = await self.client.get(
                    f"{self.base_url}/videos",
                    params={
                        "part": "snippet,statistics,contentDetails",
                        "id": ",".join(video_ids),
                        "key": self.api_key
                    }
                )
                stats_data = stats_response.json()
                
                for item in stats_data.get("items", []):
                    snippet = item.get("snippet", {})
                    stats = item.get("statistics", {})
                    
                    views = int(stats.get("viewCount", 0))
                    likes = int(stats.get("likeCount", 0))
                    comments = int(stats.get("commentCount", 0))
                    
                    published = datetime.fromisoformat(
                        snippet.get("publishedAt", "").replace("Z", "+00:00")
                    )
                    age_hours = (datetime.now(published.tzinfo) - published).total_seconds() / 3600
                    
                    results.append(DiscoveredContent(
                        platform="youtube",
                        platform_video_id=item["id"],
                        url=f"https://www.youtube.com/shorts/{item['id']}",
                        title=snippet.get("title"),
                        description=snippet.get("description"),
                        author=snippet.get("channelTitle"),
                        views=views,
                        likes=likes,
                        comments=comments,
                        upload_date=published,
                        trending_score=self.calculate_trending_score(views, likes, comments, age_hours),
                        metadata={
                            "channel_id": snippet.get("channelId"),
                            "category_id": snippet.get("categoryId"),
                            "tags": snippet.get("tags", [])
                        }
                    ))
            
            logger.info("YouTube discovery complete", count=len(results))
            return results
            
        except Exception as e:
            logger.error("YouTube discovery failed", error=str(e))
            raise
    
    async def get_video_details(self, video_id: str) -> Optional[DiscoveredContent]:
        """Get detailed information for a YouTube video"""
        try:
            response = await self.client.get(
                f"{self.base_url}/videos",
                params={
                    "part": "snippet,statistics,contentDetails",
                    "id": video_id,
                    "key": self.api_key
                }
            )
            response.raise_for_status()
            data = response.json()
            
            if not data.get("items"):
                return None
            
            item = data["items"][0]
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            
            return DiscoveredContent(
                platform="youtube",
                platform_video_id=video_id,
                url=f"https://www.youtube.com/shorts/{video_id}",
                title=snippet.get("title"),
                description=snippet.get("description"),
                author=snippet.get("channelTitle"),
                views=int(stats.get("viewCount", 0)),
                likes=int(stats.get("likeCount", 0)),
                comments=int(stats.get("commentCount", 0)),
                metadata={"channel_id": snippet.get("channelId")}
            )
            
        except Exception as e:
            logger.error("Failed to get YouTube video details", video_id=video_id, error=str(e))
            return None


class TikTokDiscovery(BaseDiscovery):
    """TikTok trending content discovery using Apify"""
    
    def __init__(self):
        super().__init__()
        self.apify_key = settings.apify_api_key
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def discover_trending(
        self,
        niche: str,
        limit: int = 100,
        timeframe: str = "24h"
    ) -> List[DiscoveredContent]:
        """Discover trending TikTok videos using Apify scraper"""
        logger.info("Discovering TikTok trends", niche=niche, limit=limit)
        
        # Use Apify TikTok scraper
        from apify_client import ApifyClient
        
        client = ApifyClient(self.apify_key)
        
        run_input = {
            "hashtags": [niche],
            "resultsPerPage": limit,
            "shouldDownloadVideos": False,
            "shouldDownloadCovers": False
        }
        
        try:
            run = client.actor("clockworks/tiktok-scraper").call(run_input=run_input)
            
            results = []
            for item in client.dataset(run["defaultDatasetId"]).iterate_items():
                views = item.get("playCount", 0)
                likes = item.get("diggCount", 0)
                comments = item.get("commentCount", 0)
                
                created = datetime.fromtimestamp(item.get("createTime", 0))
                age_hours = (datetime.now() - created).total_seconds() / 3600
                
                results.append(DiscoveredContent(
                    platform="tiktok",
                    platform_video_id=item.get("id"),
                    url=item.get("webVideoUrl"),
                    title=item.get("desc"),
                    author=item.get("authorMeta", {}).get("name"),
                    views=views,
                    likes=likes,
                    comments=comments,
                    duration_seconds=item.get("videoMeta", {}).get("duration"),
                    upload_date=created,
                    trending_score=self.calculate_trending_score(views, likes, comments, age_hours),
                    metadata={
                        "author_id": item.get("authorMeta", {}).get("id"),
                        "music": item.get("musicMeta", {}),
                        "hashtags": item.get("hashtags", [])
                    }
                ))
            
            logger.info("TikTok discovery complete", count=len(results))
            return results
            
        except Exception as e:
            logger.error("TikTok discovery failed", error=str(e))
            raise
    
    async def get_video_details(self, video_id: str) -> Optional[DiscoveredContent]:
        """Get detailed information for a TikTok video"""
        # Would need to use Apify for individual video details
        logger.warning("TikTok individual video lookup not implemented")
        return None


class InstagramDiscovery(BaseDiscovery):
    """Instagram Reels discovery using Apify"""
    
    def __init__(self):
        super().__init__()
        self.apify_key = settings.apify_api_key
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def discover_trending(
        self,
        niche: str,
        limit: int = 100,
        timeframe: str = "24h"
    ) -> List[DiscoveredContent]:
        """Discover trending Instagram Reels using Apify scraper"""
        logger.info("Discovering Instagram trends", niche=niche, limit=limit)
        
        from apify_client import ApifyClient
        
        client = ApifyClient(self.apify_key)
        
        run_input = {
            "hashtags": [niche],
            "resultsLimit": limit
        }
        
        try:
            run = client.actor("apify/instagram-scraper").call(run_input=run_input)
            
            results = []
            for item in client.dataset(run["defaultDatasetId"]).iterate_items():
                if item.get("type") != "Video":
                    continue
                
                views = item.get("videoViewCount", 0)
                likes = item.get("likesCount", 0)
                comments = item.get("commentsCount", 0)
                
                timestamp = item.get("timestamp")
                created = datetime.fromisoformat(timestamp) if timestamp else datetime.now()
                age_hours = (datetime.now() - created).total_seconds() / 3600
                
                results.append(DiscoveredContent(
                    platform="instagram",
                    platform_video_id=item.get("id"),
                    url=item.get("url"),
                    title=item.get("caption"),
                    author=item.get("ownerUsername"),
                    views=views,
                    likes=likes,
                    comments=comments,
                    duration_seconds=item.get("videoDuration"),
                    upload_date=created,
                    trending_score=self.calculate_trending_score(views, likes, comments, age_hours),
                    metadata={
                        "owner_id": item.get("ownerId"),
                        "hashtags": item.get("hashtags", [])
                    }
                ))
            
            logger.info("Instagram discovery complete", count=len(results))
            return results
            
        except Exception as e:
            logger.error("Instagram discovery failed", error=str(e))
            raise
    
    async def get_video_details(self, video_id: str) -> Optional[DiscoveredContent]:
        """Get detailed information for an Instagram video"""
        logger.warning("Instagram individual video lookup not implemented")
        return None


class SnapchatDiscovery(BaseDiscovery):
    """Snapchat Spotlight discovery"""
    
    def __init__(self):
        super().__init__()
        self.apify_key = settings.apify_api_key
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def discover_trending(
        self,
        niche: str,
        limit: int = 100,
        timeframe: str = "24h"
    ) -> List[DiscoveredContent]:
        """Discover trending Snapchat Spotlight content"""
        logger.info("Discovering Snapchat trends", niche=niche, limit=limit)
        
        # Snapchat Spotlight doesn't have public API
        # Would need custom scraper or Apify actor
        logger.warning("Snapchat discovery requires custom implementation")
        return []
    
    async def get_video_details(self, video_id: str) -> Optional[DiscoveredContent]:
        """Get detailed information for a Snapchat video"""
        logger.warning("Snapchat individual video lookup not implemented")
        return None
