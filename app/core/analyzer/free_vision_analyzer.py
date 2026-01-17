"""Free vision analyzer using computer vision techniques instead of GPT-4."""

import base64
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path
import structlog
import numpy as np

from app.core.analyzer.vision_analyzer import AnalysisResult
from app.core.analyzer.quality_checker import QualityChecker
from app.core.analyzer.watermark_detector import WatermarkDetector

logger = structlog.get_logger()


class FreeVisionAnalyzer:
    """
    Free vision analyzer using computer vision and rule-based analysis.
    
    Uses OpenCV, quality checks, and watermark detection instead of GPT-4.
    Provides similar functionality without API costs.
    """
    
    def __init__(self):
        self.quality_checker = QualityChecker()
        self.watermark_detector = WatermarkDetector()
    
    def _extract_frames(
        self,
        video_path: str,
        count: int = 3,
        quality: int = 85
    ) -> List[np.ndarray]:
        """Extract key frames from video."""
        try:
            import cv2
        except ImportError:
            raise ImportError("Please install opencv-python: pip install opencv-python")
        
        cap = cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            logger.error(f"Could not open video: {video_path}")
            return []
        
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        if total_frames <= 0:
            logger.error(f"Invalid frame count for video: {video_path}")
            cap.release()
            return []
        
        # Calculate frame indices
        if count == 1:
            frame_indices = [total_frames // 2]
        else:
            start_offset = max(1, int(total_frames * 0.05))
            end_offset = min(total_frames - 1, int(total_frames * 0.95))
            frame_indices = np.linspace(start_offset, end_offset, count, dtype=int)
        
        frames = []
        for idx in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            
            if ret and frame is not None:
                # Resize if too large
                max_dim = max(width, height)
                if max_dim > 1024:
                    scale = 1024 / max_dim
                    new_width = int(width * scale)
                    new_height = int(height * scale)
                    frame = cv2.resize(frame, (new_width, new_height))
                frames.append(frame)
        
        cap.release()
        return frames
    
    def _get_video_metadata(self, video_path: str) -> Dict[str, Any]:
        """Extract basic metadata from video file."""
        try:
            import cv2
            
            cap = cv2.VideoCapture(video_path)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = frame_count / fps if fps > 0 else 0
            
            cap.release()
            
            is_vertical = height > width
            aspect_ratio = height / width if width > 0 else 0
            
            return {
                "width": width,
                "height": height,
                "fps": fps,
                "duration_seconds": duration,
                "frame_count": frame_count,
                "is_vertical": is_vertical,
                "aspect_ratio": round(aspect_ratio, 2)
            }
        except Exception as e:
            logger.error(f"Failed to get video metadata: {e}")
            return {}
    
    def _analyze_frame_quality(self, frame: np.ndarray) -> Dict[str, Any]:
        """Analyze frame quality using computer vision."""
        try:
            import cv2
            
            # Convert to grayscale for analysis
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Calculate sharpness (Laplacian variance)
            laplacian = cv2.Laplacian(gray, cv2.CV_64F)
            sharpness = laplacian.var()
            
            # Calculate brightness
            brightness = np.mean(gray)
            
            # Calculate contrast (standard deviation)
            contrast = np.std(gray)
            
            # Detect blur (lower variance = more blur)
            is_blurry = sharpness < 100
            
            # Check for black bars (edges with low variance)
            h, w = gray.shape
            top_edge = gray[:h//10, :]
            bottom_edge = gray[-h//10:, :]
            left_edge = gray[:, :w//10]
            right_edge = gray[:, -w//10:]
            
            edge_vars = [
                np.var(top_edge),
                np.var(bottom_edge),
                np.var(left_edge),
                np.var(right_edge)
            ]
            
            # If edges have very low variance, likely black bars
            has_black_bars = any(var < 50 for var in edge_vars)
            
            # Quality score (0-1) based on multiple factors
            quality_score = min(1.0, (
                (min(sharpness, 500) / 500) * 0.4 +  # Sharpness (40%)
                (min(brightness, 200) / 200) * 0.3 +  # Brightness (30%)
                (min(contrast, 100) / 100) * 0.3      # Contrast (30%)
            ))
            
            return {
                "sharpness": float(sharpness),
                "brightness": float(brightness),
                "contrast": float(contrast),
                "is_blurry": is_blurry,
                "has_black_bars": has_black_bars,
                "quality_score": quality_score
            }
        except Exception as e:
            logger.error(f"Frame analysis failed: {e}")
            return {"quality_score": 0.5}
    
    def _detect_topics_from_metadata(self, metadata: Dict[str, Any], niche: str) -> List[str]:
        """Simple topic detection based on video metadata and niche."""
        topics = []
        
        # Extract keywords from niche
        niche_lower = niche.lower()
        if "gaming" in niche_lower or "game" in niche_lower:
            topics.append("gaming")
        if "cooking" in niche_lower or "food" in niche_lower:
            topics.append("cooking")
        if "tech" in niche_lower or "technology" in niche_lower:
            topics.append("technology")
        if "fitness" in niche_lower or "workout" in niche_lower:
            topics.append("fitness")
        if "comedy" in niche_lower or "funny" in niche_lower:
            topics.append("comedy")
        
        return topics
    
    def _calculate_relevance_score(self, metadata: Dict[str, Any], niche: str) -> float:
        """Calculate relevance score based on metadata and niche keywords."""
        # Simple keyword matching
        niche_lower = niche.lower()
        video_info = f"{metadata.get('title', '')} {metadata.get('description', '')}".lower()
        
        # Count keyword matches
        niche_words = set(niche_lower.split())
        video_words = set(video_info.split())
        
        if not niche_words:
            return 0.5  # Default if no niche specified
        
        matches = len(niche_words.intersection(video_words))
        relevance = min(1.0, matches / max(len(niche_words), 1))
        
        return relevance
    
    def _calculate_virality_potential(
        self,
        views: int,
        likes: int,
        comments: int,
        upload_date: Any,
        duration: float
    ) -> float:
        """Calculate virality potential based on engagement metrics."""
        from datetime import datetime, timedelta
        
        # Engagement rate
        if views > 0:
            engagement_rate = (likes + comments * 2) / views
        else:
            engagement_rate = 0
        
        # Time decay (newer = better)
        if isinstance(upload_date, datetime):
            age_hours = (datetime.now() - upload_date).total_seconds() / 3600
            time_score = max(0, 1 - (age_hours / 720))  # Decay over 30 days
        else:
            time_score = 0.5
        
        # Duration score (shorts are typically 15-60 seconds)
        if 15 <= duration <= 60:
            duration_score = 1.0
        elif 10 <= duration < 15 or 60 < duration <= 90:
            duration_score = 0.7
        else:
            duration_score = 0.4
        
        # View velocity (more views = higher potential)
        view_score = min(1.0, views / 1000000)  # Normalize to 1M views
        
        # Combined score
        virality = (
            engagement_rate * 0.4 +
            time_score * 0.2 +
            duration_score * 0.2 +
            view_score * 0.2
        )
        
        return min(1.0, virality)
    
    async def analyze_video(
        self,
        video_path: str,
        niche_context: str,
        content_id: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> AnalysisResult:
        """
        Analyze a video using free computer vision techniques.
        
        Args:
            video_path: Path to the video file
            niche_context: Content niche for relevance evaluation
            content_id: Optional ID for tracking
            metadata: Optional video metadata (views, likes, etc.)
            
        Returns:
            AnalysisResult with comprehensive evaluation
        """
        result = AnalysisResult(content_id=content_id)
        metadata = metadata or {}
        
        # Get video metadata
        video_meta = self._get_video_metadata(video_path)
        result.is_vertical = video_meta.get("is_vertical", False)
        
        # Check aspect ratio for black bars
        aspect_ratio = video_meta.get("aspect_ratio", 0)
        if aspect_ratio < 1.5 or aspect_ratio > 2.0:
            if video_meta.get("is_vertical"):
                result.has_black_bars = True
        
        # Extract frames
        frames = self._extract_frames(video_path, count=3)
        
        if not frames:
            result.rejection_reasons.append("Could not extract frames from video")
            return result
        
        # Analyze frames
        quality_scores = []
        watermark_detected = False
        black_bars_detected = False
        
        for frame in frames:
            # Quality analysis
            frame_analysis = self._analyze_frame_quality(frame)
            quality_scores.append(frame_analysis.get("quality_score", 0.5))
            
            # Watermark detection
            watermark_result = self.watermark_detector.detect_in_frame(
                frame,
                check_corners=True,
                check_templates=True,
                check_text=False
            )
            if watermark_result.has_watermark:
                watermark_detected = True
            
            # Black bars detection
            if frame_analysis.get("has_black_bars", False):
                black_bars_detected = True
        
        # Aggregate results
        result.visual_quality_score = np.mean(quality_scores) if quality_scores else 0.5
        result.has_watermark = watermark_detected
        result.has_black_bars = black_bars_detected or result.has_black_bars
        
        # Relevance score
        result.relevance_score = self._calculate_relevance_score(metadata, niche_context)
        
        # Virality potential
        result.virality_potential = self._calculate_virality_potential(
            views=metadata.get("views", 0),
            likes=metadata.get("likes", 0),
            comments=metadata.get("comments", 0),
            upload_date=metadata.get("upload_date"),
            duration=video_meta.get("duration_seconds", 0)
        )
        
        # Detected topics
        result.detected_topics = self._detect_topics_from_metadata(metadata, niche_context)
        
        # Generate simple captions
        if metadata.get("title"):
            result.caption_suggestion = metadata["title"][:100]
        else:
            result.caption_suggestion = f"Check out this {niche_context} content!"
        
        # Description
        if metadata.get("description"):
            result.description_suggestion = metadata["description"][:300]
        else:
            result.description_suggestion = f"Amazing {niche_context} content you don't want to miss!"
        
        # Sentiment (neutral by default, could be enhanced)
        result.sentiment = "neutral"
        
        # Determine recommendation
        result.recommended = (
            result.is_safe_content and
            not result.has_watermark and
            not result.has_black_bars and
            result.is_vertical and
            result.visual_quality_score >= 0.5 and
            result.relevance_score >= 0.4
        )
        
        if not result.recommended:
            if result.has_watermark:
                result.rejection_reasons.append("Watermark detected")
            if result.has_black_bars:
                result.rejection_reasons.append("Black bars detected")
            if not result.is_vertical:
                result.rejection_reasons.append("Not vertical format")
            if result.visual_quality_score < 0.5:
                result.rejection_reasons.append("Low visual quality")
            if result.relevance_score < 0.4:
                result.rejection_reasons.append("Low relevance to niche")
        
        logger.info(
            "Free video analysis complete",
            content_id=content_id,
            recommended=result.recommended,
            quality=result.visual_quality_score,
            relevance=result.relevance_score
        )
        
        return result
    
    async def batch_analyze(
        self,
        video_paths: List[Tuple[str, str]],  # (path, content_id)
        niche_context: str,
        max_concurrent: int = 3
    ) -> List[AnalysisResult]:
        """Analyze multiple videos with concurrency control."""
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def analyze_with_limit(path: str, content_id: str):
            async with semaphore:
                return await self.analyze_video(path, niche_context, content_id)
        
        tasks = [
            analyze_with_limit(path, cid)
            for path, cid in video_paths
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle exceptions
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Batch analysis failed for {video_paths[i]}: {result}")
                error_result = AnalysisResult(
                    content_id=video_paths[i][1],
                    rejection_reasons=[str(result)]
                )
                final_results.append(error_result)
            else:
                final_results.append(result)
        
        return final_results
