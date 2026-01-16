"""AI-powered video analysis module"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import base64
import io
from pathlib import Path
import httpx
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential
import structlog
from PIL import Image
import cv2
import numpy as np

from app.config import settings

logger = structlog.get_logger()


@dataclass
class AnalysisResult:
    """Video analysis results"""
    quality_score: float  # 0-1
    virality_score: float  # 0-1
    relevance_score: float  # 0-1
    content_summary: str
    detected_topics: List[str]
    visual_analysis: Dict[str, Any]
    sentiment: str  # 'positive', 'negative', 'neutral'
    recommended: bool


class VideoAnalyzer:
    """AI-powered video content analyzer using GPT-4 Vision"""
    
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model
        self.max_tokens = settings.openai_max_tokens
    
    async def analyze_video(
        self,
        video_path: str,
        niche: str,
        num_frames: int = 5
    ) -> AnalysisResult:
        """Analyze a video using GPT-4 Vision"""
        logger.info("Analyzing video", path=video_path, niche=niche)
        
        # Extract frames from video
        frames = self._extract_frames(video_path, num_frames)
        
        if not frames:
            raise ValueError(f"Could not extract frames from {video_path}")
        
        # Encode frames to base64
        encoded_frames = [self._encode_frame(frame) for frame in frames]
        
        # Build analysis prompt
        prompt = self._build_analysis_prompt(niche)
        
        # Send to GPT-4 Vision
        analysis = await self._analyze_with_gpt4v(encoded_frames, prompt)
        
        logger.info("Video analysis complete", 
                   quality=analysis.quality_score,
                   virality=analysis.virality_score)
        
        return analysis
    
    def _extract_frames(
        self,
        video_path: str,
        num_frames: int = 5
    ) -> List[np.ndarray]:
        """Extract evenly spaced frames from video"""
        cap = cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            logger.error("Could not open video", path=video_path)
            return []
        
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        if total_frames == 0:
            return []
        
        # Calculate frame indices to extract
        indices = np.linspace(0, total_frames - 1, num_frames, dtype=int)
        
        frames = []
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if ret:
                # Convert BGR to RGB
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frames.append(frame_rgb)
        
        cap.release()
        return frames
    
    def _encode_frame(self, frame: np.ndarray) -> str:
        """Encode frame to base64 string"""
        img = Image.fromarray(frame)
        
        # Resize if too large
        max_size = 1024
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        return base64.b64encode(buffer.getvalue()).decode()
    
    def _build_analysis_prompt(self, niche: str) -> str:
        """Build the analysis prompt for GPT-4 Vision"""
        return f"""Analyze this short-form video for the "{niche}" niche.

Evaluate the following aspects and provide scores from 0 to 1:

1. **Quality Score**: Visual quality, production value, clarity, lighting, composition
2. **Virality Score**: How likely this content is to go viral based on:
   - Hook strength (first 3 seconds engagement potential)
   - Emotional impact
   - Shareability
   - Trend alignment
3. **Relevance Score**: How relevant is this to the "{niche}" niche

Also provide:
- A brief content summary (2-3 sentences)
- Detected topics/themes (list of keywords)
- Overall sentiment (positive/negative/neutral)
- Visual elements analysis (colors, text overlays, faces, objects)
- Whether you recommend this video for use (true/false)

Respond in JSON format:
{{
    "quality_score": 0.0-1.0,
    "virality_score": 0.0-1.0,
    "relevance_score": 0.0-1.0,
    "content_summary": "...",
    "detected_topics": ["topic1", "topic2"],
    "visual_analysis": {{
        "dominant_colors": ["color1", "color2"],
        "has_text_overlay": true/false,
        "has_faces": true/false,
        "scene_type": "indoor/outdoor/animated/etc",
        "production_level": "professional/amateur/ugc"
    }},
    "sentiment": "positive/negative/neutral",
    "recommended": true/false,
    "recommendation_reason": "..."
}}"""
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def _analyze_with_gpt4v(
        self,
        encoded_frames: List[str],
        prompt: str
    ) -> AnalysisResult:
        """Send frames to GPT-4 Vision for analysis"""
        # Build message content with images
        content = [{"type": "text", "text": prompt}]
        
        for i, frame in enumerate(encoded_frames):
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{frame}",
                    "detail": "low"  # Use low detail for cost efficiency
                }
            })
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": content
                    }
                ],
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"}
            )
            
            import json
            result = json.loads(response.choices[0].message.content)
            
            return AnalysisResult(
                quality_score=float(result.get("quality_score", 0)),
                virality_score=float(result.get("virality_score", 0)),
                relevance_score=float(result.get("relevance_score", 0)),
                content_summary=result.get("content_summary", ""),
                detected_topics=result.get("detected_topics", []),
                visual_analysis=result.get("visual_analysis", {}),
                sentiment=result.get("sentiment", "neutral"),
                recommended=result.get("recommended", False)
            )
            
        except Exception as e:
            logger.error("GPT-4 Vision analysis failed", error=str(e))
            raise
    
    async def batch_analyze(
        self,
        video_paths: List[str],
        niche: str
    ) -> List[Tuple[str, Optional[AnalysisResult]]]:
        """Analyze multiple videos"""
        results = []
        
        for path in video_paths:
            try:
                analysis = await self.analyze_video(path, niche)
                results.append((path, analysis))
            except Exception as e:
                logger.error("Failed to analyze video", path=path, error=str(e))
                results.append((path, None))
        
        return results
    
    def filter_recommended(
        self,
        results: List[Tuple[str, Optional[AnalysisResult]]],
        min_quality: float = 0.6,
        min_virality: float = 0.5,
        min_relevance: float = 0.7
    ) -> List[Tuple[str, AnalysisResult]]:
        """Filter analysis results to only recommended videos"""
        filtered = []
        
        for path, analysis in results:
            if analysis is None:
                continue
            
            if (
                analysis.recommended and
                analysis.quality_score >= min_quality and
                analysis.virality_score >= min_virality and
                analysis.relevance_score >= min_relevance
            ):
                filtered.append((path, analysis))
        
        # Sort by combined score
        filtered.sort(
            key=lambda x: (
                x[1].quality_score * 0.3 +
                x[1].virality_score * 0.4 +
                x[1].relevance_score * 0.3
            ),
            reverse=True
        )
        
        return filtered
