"""Trend discovery API endpoints"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from typing import List, Optional, Literal
from datetime import datetime, timedelta

from app.core.database import get_db
from app.models.platform_content import PlatformContent
from app.schemas.video import TrendingContentResponse
from app.core.discovery import (
    YouTubeDiscovery,
    TikTokDiscovery,
    InstagramDiscovery,
    SnapchatDiscovery
)

router = APIRouter()

Platform = Literal["youtube", "tiktok", "instagram", "snapchat"]


@router.get("/", response_model=List[TrendingContentResponse])
async def get_trends(
    platforms: Optional[List[Platform]] = Query(None),
    niche: Optional[str] = Query(None),
    timeframe: str = Query("24h", regex="^(1h|6h|12h|24h|7d|30d)$"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db)
):
    """Get aggregated trending content across platforms"""
    # Calculate time threshold
    timeframe_map = {
        "1h": timedelta(hours=1),
        "6h": timedelta(hours=6),
        "12h": timedelta(hours=12),
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30)
    }
    since = datetime.utcnow() - timeframe_map[timeframe]
    
    query = select(PlatformContent).where(
        PlatformContent.discovered_at >= since
    ).order_by(desc(PlatformContent.trending_score))
    
    if platforms:
        query = query.where(PlatformContent.platform.in_(platforms))
    
    query = query.limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{platform}", response_model=List[TrendingContentResponse])
async def get_platform_trends(
    platform: Platform,
    niche: Optional[str] = Query(None),
    timeframe: str = Query("24h", regex="^(1h|6h|12h|24h|7d|30d)$"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db)
):
    """Get trending content from a specific platform"""
    # Calculate time threshold
    timeframe_map = {
        "1h": timedelta(hours=1),
        "6h": timedelta(hours=6),
        "12h": timedelta(hours=12),
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30)
    }
    since = datetime.utcnow() - timeframe_map[timeframe]
    
    query = select(PlatformContent).where(
        PlatformContent.platform == platform,
        PlatformContent.discovered_at >= since
    ).order_by(desc(PlatformContent.trending_score))
    
    query = query.limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/discover/{platform}")
async def trigger_discovery(
    platform: Platform,
    niche: str = Query(..., min_length=1),
    limit: int = Query(100, ge=10, le=500)
):
    """Manually trigger trend discovery for a platform"""
    discovery_map = {
        "youtube": YouTubeDiscovery,
        "tiktok": TikTokDiscovery,
        "instagram": InstagramDiscovery,
        "snapchat": SnapchatDiscovery
    }
    
    discoverer = discovery_map[platform]()
    
    # This would normally be an async task
    # For now, return acknowledgment
    return {
        "message": f"Discovery initiated for {platform}",
        "niche": niche,
        "limit": limit,
        "status": "processing"
    }


@router.get("/stats/summary")
async def get_trend_stats(
    db: AsyncSession = Depends(get_db)
):
    """Get summary statistics for discovered content"""
    # Total content count by platform
    platform_counts = await db.execute(
        select(
            PlatformContent.platform,
            func.count(PlatformContent.content_id)
        ).group_by(PlatformContent.platform)
    )
    
    # Content discovered in last 24h
    yesterday = datetime.utcnow() - timedelta(days=1)
    recent_count = await db.execute(
        select(func.count(PlatformContent.content_id)).where(
            PlatformContent.discovered_at >= yesterday
        )
    )
    
    # Top trending score
    top_trending = await db.execute(
        select(PlatformContent).order_by(
            desc(PlatformContent.trending_score)
        ).limit(1)
    )
    
    return {
        "by_platform": {row[0]: row[1] for row in platform_counts.all()},
        "discovered_last_24h": recent_count.scalar(),
        "top_trending": top_trending.scalar_one_or_none()
    }
