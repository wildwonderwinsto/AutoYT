"""Discovery Orchestrator - Coordinates multi-platform content discovery."""

from typing import List, Dict, Any, Optional, Set
from datetime import datetime
import asyncio
from difflib import SequenceMatcher
import structlog

from app.core.discovery.base_client import DiscoveredVideo
from app.core.discovery.youtube_client import YouTubeClient
from app.core.discovery.social_client import ApifySocialClient
from app.config import settings

logger = structlog.get_logger()


class DiscoveryOrchestrator:
    """
    Orchestrates content discovery across multiple platforms.
    
    Responsibilities:
    - Initialize and manage platform clients
    - Execute concurrent discovery across platforms
    - Deduplicate similar content
    - Merge and rank results by viral score
    - Filter content by quality thresholds
    """
    
    def __init__(self, platforms: List[str] = None):
        """
        Initialize orchestrator with specified platforms.
        
        Args:
            platforms: List of platforms to enable. 
                      Default: ["youtube", "tiktok", "instagram"]
        """
        self.enabled_platforms = platforms or ["youtube", "tiktok", "instagram"]
        self._clients: Dict[str, Any] = {}
        self._initialize_clients()
    
    def _initialize_clients(self):
        """Initialize platform clients based on configuration."""
        if "youtube" in self.enabled_platforms:
            try:
                from app.config import settings
                self._clients["youtube"] = YouTubeClient(
                    use_api=not settings.use_free_discovery
                )
                logger.info("YouTube client initialized")
            except Exception as e:
                logger.error(f"Failed to initialize YouTube client: {e}")
        
        for platform in ["tiktok", "instagram", "snapchat"]:
            if platform in self.enabled_platforms:
                try:
                    self._clients[platform] = ApifySocialClient(
                        platform,
                        use_free=settings.use_free_discovery
                    )
                    logger.info(f"{platform.title()} client initialized")
                except Exception as e:
                    logger.error(f"Failed to initialize {platform} client: {e}")
    
    async def discover_content(
        self,
        query: str,
        timeframe_hours: int = 720,  # Default 30 days
        per_platform_limit: int = 50,
        min_viral_score: float = 0.0,
        min_views: int = 0,
        deduplicate: bool = True
    ) -> List[DiscoveredVideo]:
        """
        Discover trending content across all enabled platforms.
        
        Args:
            query: Search query or niche (e.g., "gaming", "#fitness")
            timeframe_hours: How far back to search (default 30 days)
            per_platform_limit: Max results per platform
            min_viral_score: Minimum viral score threshold (0-100)
            min_views: Minimum view count filter
            deduplicate: Whether to remove similar content
            
        Returns:
            List of DiscoveredVideo sorted by viral score
        """
        logger.info(
            "Starting multi-platform discovery",
            query=query,
            platforms=list(self._clients.keys()),
            timeframe_hours=timeframe_hours
        )
        
        # Create discovery tasks for all platforms
        tasks = []
        for platform, client in self._clients.items():
            task = asyncio.create_task(
                self._safe_discover(
                    client, query, timeframe_hours, per_platform_limit
                ),
                name=f"discover_{platform}"
            )
            tasks.append(task)
        
        # Wait for all platforms to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Collect all videos
        all_videos: List[DiscoveredVideo] = []
        platform_stats = {}
        
        for platform, result in zip(self._clients.keys(), results):
            if isinstance(result, Exception):
                logger.error(f"Discovery failed for {platform}: {result}")
                platform_stats[platform] = {"status": "failed", "error": str(result)}
                continue
            
            all_videos.extend(result)
            platform_stats[platform] = {"status": "success", "count": len(result)}
        
        logger.info("Platform discovery results", stats=platform_stats)
        
        # Post-processing pipeline
        # 1. Apply minimum filters
        filtered_videos = [
            v for v in all_videos
            if v.trending_score >= min_viral_score and v.views >= min_views
        ]
        
        # 2. Deduplicate
        if deduplicate:
            unique_videos = self._deduplicate_videos(filtered_videos)
        else:
            unique_videos = filtered_videos
        
        # 3. Sort by viral score
        unique_videos.sort(key=lambda v: v.trending_score, reverse=True)
        
        logger.info(
            "Discovery complete",
            total_found=len(all_videos),
            after_filter=len(filtered_videos),
            after_dedup=len(unique_videos)
        )
        
        return unique_videos
    
    async def _safe_discover(
        self,
        client,
        query: str,
        timeframe_hours: int,
        limit: int
    ) -> List[DiscoveredVideo]:
        """Wrapper to safely execute discovery with error handling."""
        try:
            return await client.discover_trending(query, timeframe_hours, limit)
        except Exception as e:
            logger.error(f"Client discovery error: {e}")
            return []
    
    def _deduplicate_videos(
        self,
        videos: List[DiscoveredVideo],
        similarity_threshold: float = 0.85
    ) -> List[DiscoveredVideo]:
        """
        Remove duplicate and near-duplicate videos.
        
        Uses URL exact matching and title similarity for deduplication.
        When duplicates are found, keeps the one with higher viral score.
        """
        if not videos:
            return []
        
        seen_urls: Set[str] = set()
        seen_titles: List[tuple] = []  # (title, video) pairs for similarity check
        unique_videos: List[DiscoveredVideo] = []
        
        for video in videos:
            # Exact URL match
            if video.url in seen_urls:
                continue
            
            # Title similarity check (fuzzy matching)
            is_duplicate = False
            for existing_title, existing_video in seen_titles:
                similarity = self._calculate_similarity(video.title, existing_title)
                if similarity >= similarity_threshold:
                    # Keep the one with higher score
                    if video.trending_score > existing_video.trending_score:
                        # Replace existing with new
                        unique_videos.remove(existing_video)
                        seen_titles.remove((existing_title, existing_video))
                        unique_videos.append(video)
                        seen_titles.append((video.title, video))
                        seen_urls.add(video.url)
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                unique_videos.append(video)
                seen_urls.add(video.url)
                if video.title:
                    seen_titles.append((video.title, video))
        
        return unique_videos
    
    def _calculate_similarity(self, title1: str, title2: str) -> float:
        """Calculate similarity ratio between two titles."""
        if not title1 or not title2:
            return 0.0
        
        # Normalize: lowercase, remove extra whitespace
        t1 = " ".join(title1.lower().split())
        t2 = " ".join(title2.lower().split())
        
        return SequenceMatcher(None, t1, t2).ratio()
    
    async def discover_for_ranking(
        self,
        niche: str,
        ranking_count: int = 10,
        **kwargs
    ) -> List[DiscoveredVideo]:
        """
        Discover content specifically for creating ranking videos.
        
        Fetches more content than needed, then returns the top N
        by viral score to ensure quality.
        
        Args:
            niche: Content niche/category
            ranking_count: Number of videos needed for the ranking
            **kwargs: Additional filters passed to discover_content
            
        Returns:
            Top N videos for the ranking
        """
        # Fetch 5x more than needed to ensure quality selection
        per_platform = max(ranking_count * 2, 30)
        
        all_content = await self.discover_content(
            query=niche,
            per_platform_limit=per_platform,
            **kwargs
        )
        
        # Return top videos for the ranking
        return all_content[:ranking_count]
    
    async def close(self):
        """Close all platform client connections."""
        for client in self._clients.values():
            if hasattr(client, "close"):
                await client.close()


async def create_orchestrator(platforms: List[str] = None) -> DiscoveryOrchestrator:
    """Factory function to create and initialize an orchestrator."""
    return DiscoveryOrchestrator(platforms)
