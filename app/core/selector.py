"""Content selector for ranking and filtering analyzed videos."""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from sqlalchemy import select, text, and_
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.database import async_session_maker
from app.models.platform_content import PlatformContent
from app.models.video_analysis import VideoAnalysis
from app.models.downloaded_video import DownloadedVideo

logger = structlog.get_logger()


@dataclass
class RankedClip:
    """A clip selected for the final compilation."""
    content_id: str
    rank: int
    url: str
    local_path: str
    title: str
    author: str
    
    # Scores
    trending_score: float
    quality_score: float
    relevance_score: float
    composite_score: float
    
    # AI-generated content
    caption_suggestion: str = ""
    description_suggestion: str = ""
    
    # Metadata
    duration_seconds: float = 0.0
    platform: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "content_id": self.content_id,
            "rank": self.rank,
            "url": self.url,
            "local_path": self.local_path,
            "title": self.title,
            "author": self.author,
            "trending_score": self.trending_score,
            "quality_score": self.quality_score,
            "relevance_score": self.relevance_score,
            "composite_score": self.composite_score,
            "caption_suggestion": self.caption_suggestion,
            "description_suggestion": self.description_suggestion,
            "duration_seconds": self.duration_seconds,
            "platform": self.platform
        }


@dataclass
class SelectionConfig:
    """Configuration for content selection."""
    # Weighting factors for composite score
    trending_weight: float = 0.4
    quality_weight: float = 0.3
    relevance_weight: float = 0.3
    
    # Minimum thresholds
    min_quality_score: float = 0.5
    min_relevance_score: float = 0.4
    min_trending_score: float = 0.0
    
    # Selection limits
    max_clips: int = 10
    max_per_author: int = 2  # Prevent single creator domination
    
    # Duration constraints
    min_duration_seconds: float = 5.0
    max_duration_seconds: float = 60.0
    
    # Platform diversity
    require_platform_diversity: bool = False
    
    def validate(self):
        """Validate configuration weights sum to 1."""
        total = self.trending_weight + self.quality_weight + self.relevance_weight
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Score weights must sum to 1.0, got {total}")


class ContentSelector:
    """
    Selects the best clips for the final compilation.
    
    Uses a weighted scoring algorithm combining:
    - Trending score (viral potential from Stage 2)
    - Quality score (visual quality from Stage 3)
    - Relevance score (niche relevance from Stage 3)
    
    Applies additional filtering for:
    - Author diversity (prevent single creator domination)
    - Duration constraints
    - Platform variety
    """
    
    def __init__(self, config: SelectionConfig = None):
        self.config = config or SelectionConfig()
        self.config.validate()
    
    def _calculate_composite_score(
        self,
        trending: float,
        quality: float,
        relevance: float
    ) -> float:
        """Calculate weighted composite score."""
        # Normalize trending to 0-1 (it's 0-100)
        normalized_trending = trending / 100.0 if trending > 1 else trending
        
        score = (
            normalized_trending * self.config.trending_weight +
            quality * self.config.quality_weight +
            relevance * self.config.relevance_weight
        )
        
        return round(score, 4)
    
    async def select_top_clips(
        self,
        job_id: str,
        limit: int = None,
        session: AsyncSession = None
    ) -> List[RankedClip]:
        """
        Select the best clips for a job based on composite scoring.
        
        Args:
            job_id: Job UUID
            limit: Override max clips from config
            session: Optional existing database session
            
        Returns:
            List of RankedClip sorted by composite score
        """
        limit = limit or self.config.max_clips
        
        async def _select(db: AsyncSession):
            # Query joining content, analysis, and downloads
            query = text("""
                SELECT 
                    pc.content_id,
                    pc.url,
                    pc.title,
                    pc.author,
                    pc.platform,
                    pc.trending_score,
                    va.quality_score,
                    va.relevance_score,
                    va.visual_analysis,
                    dv.local_path,
                    dv.duration_seconds
                FROM platform_content pc
                INNER JOIN video_analysis va ON pc.content_id = va.content_id
                INNER JOIN downloaded_videos dv ON pc.content_id = dv.content_id
                WHERE pc.job_id = :job_id
                AND va.recommended = true
                AND dv.local_path IS NOT NULL
                ORDER BY 
                    (pc.trending_score / 100.0 * :tw + va.quality_score * :qw + va.relevance_score * :rw) DESC
            """)
            
            result = await db.execute(
                query,
                {
                    "job_id": job_id,
                    "tw": self.config.trending_weight,
                    "qw": self.config.quality_weight,
                    "rw": self.config.relevance_weight
                }
            )
            
            rows = result.mappings().all()
            
            # Apply additional filters and diversity rules
            selected = []
            author_counts = {}
            platform_counts = {}
            
            for row in rows:
                # Check author limit
                author = row.get("author", "unknown")
                if author_counts.get(author, 0) >= self.config.max_per_author:
                    continue
                
                # Check duration
                duration = row.get("duration_seconds", 0) or 0
                if duration < self.config.min_duration_seconds:
                    continue
                if duration > self.config.max_duration_seconds:
                    continue
                
                # Calculate composite score
                composite = self._calculate_composite_score(
                    row.get("trending_score", 0),
                    row.get("quality_score", 0),
                    row.get("relevance_score", 0)
                )
                
                # Extract AI suggestions
                visual_analysis = row.get("visual_analysis") or {}
                caption = visual_analysis.get("caption_suggestion", "")
                description = visual_analysis.get("description_suggestion", "")
                
                clip = RankedClip(
                    content_id=str(row["content_id"]),
                    rank=len(selected) + 1,
                    url=row["url"],
                    local_path=row["local_path"],
                    title=row.get("title", ""),
                    author=author,
                    trending_score=row.get("trending_score", 0),
                    quality_score=row.get("quality_score", 0),
                    relevance_score=row.get("relevance_score", 0),
                    composite_score=composite,
                    caption_suggestion=caption,
                    description_suggestion=description,
                    duration_seconds=duration,
                    platform=row.get("platform", "")
                )
                
                selected.append(clip)
                author_counts[author] = author_counts.get(author, 0) + 1
                
                platform = row.get("platform", "unknown")
                platform_counts[platform] = platform_counts.get(platform, 0) + 1
                
                if len(selected) >= limit:
                    break
            
            logger.info(
                f"Selected {len(selected)} clips for job",
                job_id=job_id,
                platform_distribution=platform_counts
            )
            
            return selected
        
        if session:
            return await _select(session)
        else:
            async with async_session_maker() as db:
                return await _select(db)
    
    async def get_selection_summary(self, job_id: str) -> Dict[str, Any]:
        """Get summary statistics for content selection."""
        async with async_session_maker() as db:
            # Count total analyzed
            total_result = await db.execute(
                text("""
                    SELECT COUNT(*) as total
                    FROM platform_content pc
                    INNER JOIN video_analysis va ON pc.content_id = va.content_id
                    WHERE pc.job_id = :job_id
                """),
                {"job_id": job_id}
            )
            total = total_result.scalar() or 0
            
            # Count recommended
            recommended_result = await db.execute(
                text("""
                    SELECT COUNT(*) as recommended
                    FROM platform_content pc
                    INNER JOIN video_analysis va ON pc.content_id = va.content_id
                    WHERE pc.job_id = :job_id AND va.recommended = true
                """),
                {"job_id": job_id}
            )
            recommended = recommended_result.scalar() or 0
            
            # Count downloaded
            downloaded_result = await db.execute(
                text("""
                    SELECT COUNT(*) as downloaded
                    FROM platform_content pc
                    INNER JOIN downloaded_videos dv ON pc.content_id = dv.content_id
                    WHERE pc.job_id = :job_id
                """),
                {"job_id": job_id}
            )
            downloaded = downloaded_result.scalar() or 0
            
            # Get score averages
            score_result = await db.execute(
                text("""
                    SELECT 
                        AVG(va.quality_score) as avg_quality,
                        AVG(va.relevance_score) as avg_relevance,
                        AVG(pc.trending_score) as avg_trending
                    FROM platform_content pc
                    INNER JOIN video_analysis va ON pc.content_id = va.content_id
                    WHERE pc.job_id = :job_id AND va.recommended = true
                """),
                {"job_id": job_id}
            )
            scores = score_result.mappings().first() or {}
            
            return {
                "job_id": job_id,
                "total_analyzed": total,
                "recommended": recommended,
                "downloaded": downloaded,
                "rejection_rate": round((total - recommended) / max(total, 1) * 100, 1),
                "avg_quality_score": round(scores.get("avg_quality", 0) or 0, 3),
                "avg_relevance_score": round(scores.get("avg_relevance", 0) or 0, 3),
                "avg_trending_score": round(scores.get("avg_trending", 0) or 0, 2)
            }
    
    async def get_rejection_reasons(self, job_id: str) -> List[Dict[str, Any]]:
        """Get list of rejected videos with reasons."""
        async with async_session_maker() as db:
            result = await db.execute(
                text("""
                    SELECT 
                        pc.content_id,
                        pc.title,
                        pc.url,
                        va.visual_analysis
                    FROM platform_content pc
                    INNER JOIN video_analysis va ON pc.content_id = va.content_id
                    WHERE pc.job_id = :job_id AND va.recommended = false
                    LIMIT 50
                """),
                {"job_id": job_id}
            )
            
            rejections = []
            for row in result.mappings():
                analysis = row.get("visual_analysis") or {}
                reasons = analysis.get("rejection_reasons", [])
                
                if not reasons:
                    # Infer reasons
                    if analysis.get("has_watermark"):
                        reasons.append("Has watermark")
                    if not analysis.get("is_safe_content"):
                        reasons.append("Content not safe for ads")
                    if analysis.get("visual_quality_score", 10) < 5:
                        reasons.append("Low visual quality")
                
                rejections.append({
                    "content_id": str(row["content_id"]),
                    "title": row.get("title", "")[:50],
                    "url": row["url"],
                    "reasons": reasons
                })
            
            return rejections
