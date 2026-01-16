"""GPT-4 Vision Analyzer for video content evaluation."""

import base64
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path
import json
import structlog

from app.config import settings

logger = structlog.get_logger()


@dataclass
class AnalysisResult:
    """Result of video content analysis."""
    content_id: str = ""
    is_safe_content: bool = True
    has_watermark: bool = False
    is_vertical: bool = True
    has_black_bars: bool = False
    visual_quality_score: float = 0.0  # 0-1 normalized
    relevance_score: float = 0.0  # 0-1 normalized
    virality_potential: float = 0.0  # 0-1 normalized
    detected_topics: List[str] = field(default_factory=list)
    caption_suggestion: str = ""
    description_suggestion: str = ""
    detected_text: List[str] = field(default_factory=list)
    sentiment: str = "neutral"
    recommended: bool = False
    rejection_reasons: List[str] = field(default_factory=list)
    raw_analysis: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "content_id": self.content_id,
            "is_safe_content": self.is_safe_content,
            "has_watermark": self.has_watermark,
            "is_vertical": self.is_vertical,
            "has_black_bars": self.has_black_bars,
            "visual_quality_score": self.visual_quality_score,
            "relevance_score": self.relevance_score,
            "virality_potential": self.virality_potential,
            "detected_topics": self.detected_topics,
            "caption_suggestion": self.caption_suggestion,
            "description_suggestion": self.description_suggestion,
            "detected_text": self.detected_text,
            "sentiment": self.sentiment,
            "recommended": self.recommended,
            "rejection_reasons": self.rejection_reasons
        }


class VisionAnalyzer:
    """
    GPT-4 Vision based analyzer for video content.
    
    Extracts key frames from videos and uses AI to evaluate:
    - Content safety and appropriateness
    - Visual quality (lighting, focus, composition)
    - Watermark/overlay detection
    - Aspect ratio verification
    - Niche relevance
    - Caption/description generation
    """
    
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.openai_model
        self._client = None
    
    @property
    def client(self):
        """Lazy initialize OpenAI client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(api_key=self.api_key)
            except ImportError:
                raise ImportError("Please install openai: pip install openai")
        return self._client
    
    def _extract_frames(
        self,
        video_path: str,
        count: int = 3,
        quality: int = 85
    ) -> List[str]:
        """
        Extract key frames from video and return as base64 encoded strings.
        
        Extracts frames from start, middle, and end of video to get
        a representative sample of the content.
        
        Args:
            video_path: Path to the video file
            count: Number of frames to extract
            quality: JPEG quality (1-100)
            
        Returns:
            List of base64 encoded frame images
        """
        try:
            import cv2
            import numpy as np
        except ImportError:
            raise ImportError("Please install opencv-python: pip install opencv-python")
        
        cap = cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            logger.error(f"Could not open video: {video_path}")
            return []
        
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        if total_frames <= 0:
            logger.error(f"Invalid frame count for video: {video_path}")
            cap.release()
            return []
        
        # Calculate frame indices (start, middle points, end)
        if count == 1:
            frame_indices = [total_frames // 2]
        else:
            # Avoid first/last 5% to skip intros/outros
            start_offset = max(1, int(total_frames * 0.05))
            end_offset = min(total_frames - 1, int(total_frames * 0.95))
            frame_indices = np.linspace(start_offset, end_offset, count, dtype=int)
        
        base64_frames = []
        
        for idx in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            
            if ret and frame is not None:
                # Resize if too large (max 1024px on longest side)
                max_dim = max(width, height)
                if max_dim > 1024:
                    scale = 1024 / max_dim
                    new_width = int(width * scale)
                    new_height = int(height * scale)
                    frame = cv2.resize(frame, (new_width, new_height))
                
                # Encode as JPEG
                encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]
                _, buffer = cv2.imencode('.jpg', frame, encode_params)
                base64_str = base64.b64encode(buffer).decode('utf-8')
                base64_frames.append(base64_str)
        
        cap.release()
        
        logger.debug(
            f"Extracted {len(base64_frames)} frames",
            video=video_path,
            dimensions=f"{width}x{height}",
            total_frames=total_frames
        )
        
        return base64_frames
    
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
            
            # Determine orientation
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
    
    def _build_analysis_prompt(self, niche_context: str) -> str:
        """Build the analysis prompt for GPT-4 Vision."""
        return f"""You are a professional video editor and content curator for a YouTube Shorts channel focused on "{niche_context}".

Analyze these frames from a short video and provide a detailed assessment.

IMPORTANT: Return ONLY a valid JSON object with the following structure (no markdown, no explanation):

{{
    "is_safe_content": true/false,
    "safety_notes": "brief explanation if unsafe",
    "has_watermark": true/false,
    "watermark_type": "none/tiktok/instagram/custom/username",
    "has_black_bars": true/false,
    "is_vertical_oriented": true/false,
    "visual_quality_score": 1-10,
    "quality_issues": ["list of issues like blur, poor lighting, etc"],
    "relevance_score": 1-10,
    "relevance_reasoning": "why this is/isn't relevant to {niche_context}",
    "virality_potential": 1-10,
    "detected_topics": ["topic1", "topic2"],
    "detected_text_overlays": ["any text visible in frames"],
    "caption_suggestion": "short punchy caption (max 100 chars)",
    "description_suggestion": "2-3 sentence description for YouTube",
    "sentiment": "positive/negative/neutral/funny/dramatic",
    "recommendation": "include/exclude/maybe",
    "rejection_reasons": ["list reasons if excluded"]
}}

Evaluation Criteria:
- Visual Quality: Assess lighting, focus, resolution, camera stability
- Watermarks: Look for TikTok logo, Instagram handle, or custom watermarks (CRITICAL - reject if present)
- Black Bars: Check for pillarboxing or letterboxing (exclude if present)
- Content Safety: Must be advertiser-friendly for YouTube
- Relevance: How well does this match "{niche_context}"?
- Virality: Does this have engaging hook, good pacing, interesting content?"""
    
    async def analyze_video(
        self,
        video_path: str,
        niche_context: str,
        content_id: str = ""
    ) -> AnalysisResult:
        """
        Analyze a video using GPT-4 Vision.
        
        Args:
            video_path: Path to the video file
            niche_context: Content niche for relevance evaluation
            content_id: Optional ID for tracking
            
        Returns:
            AnalysisResult with comprehensive evaluation
        """
        result = AnalysisResult(content_id=content_id)
        
        # Get video metadata
        metadata = self._get_video_metadata(video_path)
        result.is_vertical = metadata.get("is_vertical", False)
        
        # Check aspect ratio for black bars
        aspect_ratio = metadata.get("aspect_ratio", 0)
        if aspect_ratio < 1.5 or aspect_ratio > 2.0:
            # Not a typical vertical short format
            if metadata.get("is_vertical"):
                result.has_black_bars = True
        
        # Extract frames
        frames = self._extract_frames(video_path, count=3)
        
        if not frames:
            result.rejection_reasons.append("Could not extract frames from video")
            return result
        
        try:
            # Build message content with frames
            content = [
                {
                    "type": "text",
                    "text": self._build_analysis_prompt(niche_context)
                }
            ]
            
            for i, frame_b64 in enumerate(frames):
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{frame_b64}",
                        "detail": "high"
                    }
                })
            
            # Call GPT-4 Vision
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": content
                    }
                ],
                max_tokens=1000,
                temperature=0.3
            )
            
            # Parse response
            response_text = response.choices[0].message.content
            
            # Clean response (remove markdown code blocks if present)
            if response_text.startswith("```"):
                response_text = response_text.strip("```json").strip("```").strip()
            
            analysis = json.loads(response_text)
            result.raw_analysis = analysis
            
            # Map to result
            result.is_safe_content = analysis.get("is_safe_content", True)
            result.has_watermark = analysis.get("has_watermark", False)
            result.has_black_bars = analysis.get("has_black_bars", result.has_black_bars)
            result.is_vertical = analysis.get("is_vertical_oriented", result.is_vertical)
            
            # Normalize scores to 0-1
            result.visual_quality_score = analysis.get("visual_quality_score", 5) / 10.0
            result.relevance_score = analysis.get("relevance_score", 5) / 10.0
            result.virality_potential = analysis.get("virality_potential", 5) / 10.0
            
            result.detected_topics = analysis.get("detected_topics", [])
            result.detected_text = analysis.get("detected_text_overlays", [])
            result.caption_suggestion = analysis.get("caption_suggestion", "")
            result.description_suggestion = analysis.get("description_suggestion", "")
            result.sentiment = analysis.get("sentiment", "neutral")
            result.rejection_reasons = analysis.get("rejection_reasons", [])
            
            # Determine recommendation
            recommendation = analysis.get("recommendation", "maybe")
            if recommendation == "include":
                result.recommended = True
            elif recommendation == "exclude":
                result.recommended = False
            else:
                # Auto-decide based on criteria
                result.recommended = (
                    result.is_safe_content and
                    not result.has_watermark and
                    not result.has_black_bars and
                    result.is_vertical and
                    result.visual_quality_score >= 0.5 and
                    result.relevance_score >= 0.4
                )
            
            logger.info(
                "Video analysis complete",
                content_id=content_id,
                recommended=result.recommended,
                quality=result.visual_quality_score,
                relevance=result.relevance_score
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse GPT response: {e}")
            result.rejection_reasons.append(f"Analysis parsing failed: {str(e)}")
        except Exception as e:
            logger.error(f"GPT-4 Vision analysis failed: {e}")
            result.rejection_reasons.append(f"Analysis error: {str(e)}")
        
        return result
    
    async def batch_analyze(
        self,
        video_paths: List[Tuple[str, str]],  # (path, content_id)
        niche_context: str,
        max_concurrent: int = 3
    ) -> List[AnalysisResult]:
        """
        Analyze multiple videos with concurrency control.
        
        Args:
            video_paths: List of (video_path, content_id) tuples
            niche_context: Content niche for relevance
            max_concurrent: Max concurrent API calls
            
        Returns:
            List of AnalysisResults
        """
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
