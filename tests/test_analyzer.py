"""Tests for video analyzer module"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import numpy as np


class TestVideoAnalyzer:
    """Test VideoAnalyzer class"""
    
    def test_initialization(self):
        """Test analyzer initializes with OpenAI client"""
        with patch('app.core.analyzer.AsyncOpenAI') as mock_openai:
            from app.core.analyzer import VideoAnalyzer
            
            analyzer = VideoAnalyzer()
            mock_openai.assert_called_once()
    
    def test_encode_frame(self):
        """Test frame encoding to base64"""
        with patch('app.core.analyzer.AsyncOpenAI'):
            from app.core.analyzer import VideoAnalyzer
            
            analyzer = VideoAnalyzer()
            
            # Create a small test frame
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            frame[50, 50] = [255, 0, 0]  # Red pixel
            
            encoded = analyzer._encode_frame(frame)
            
            assert isinstance(encoded, str)
            assert len(encoded) > 0
    
    def test_build_analysis_prompt(self):
        """Test analysis prompt generation"""
        with patch('app.core.analyzer.AsyncOpenAI'):
            from app.core.analyzer import VideoAnalyzer
            
            analyzer = VideoAnalyzer()
            
            prompt = analyzer._build_analysis_prompt("gaming")
            
            assert "gaming" in prompt
            assert "quality_score" in prompt.lower()
            assert "virality_score" in prompt.lower()
            assert "JSON" in prompt


class TestAnalysisResult:
    """Test AnalysisResult dataclass"""
    
    def test_result_creation(self):
        """Test creating an AnalysisResult"""
        from app.core.analyzer import AnalysisResult
        
        result = AnalysisResult(
            quality_score=0.85,
            virality_score=0.72,
            relevance_score=0.91,
            content_summary="A gaming highlight video",
            detected_topics=["gaming", "esports"],
            visual_analysis={"has_faces": True},
            sentiment="positive",
            recommended=True
        )
        
        assert result.quality_score == 0.85
        assert result.recommended is True
        assert "gaming" in result.detected_topics
    
    def test_result_score_ranges(self):
        """Test that scores are within valid range"""
        from app.core.analyzer import AnalysisResult
        
        result = AnalysisResult(
            quality_score=0.5,
            virality_score=0.5,
            relevance_score=0.5,
            content_summary="Test",
            detected_topics=[],
            visual_analysis={},
            sentiment="neutral",
            recommended=False
        )
        
        assert 0 <= result.quality_score <= 1
        assert 0 <= result.virality_score <= 1
        assert 0 <= result.relevance_score <= 1


class TestFilterRecommended:
    """Test video filtering logic"""
    
    def test_filter_by_thresholds(self):
        """Test filtering by score thresholds"""
        with patch('app.core.analyzer.AsyncOpenAI'):
            from app.core.analyzer import VideoAnalyzer, AnalysisResult
            
            analyzer = VideoAnalyzer()
            
            results = [
                ("/path/1.mp4", AnalysisResult(
                    quality_score=0.9,
                    virality_score=0.8,
                    relevance_score=0.9,
                    content_summary="High quality",
                    detected_topics=[],
                    visual_analysis={},
                    sentiment="positive",
                    recommended=True
                )),
                ("/path/2.mp4", AnalysisResult(
                    quality_score=0.3,
                    virality_score=0.2,
                    relevance_score=0.4,
                    content_summary="Low quality",
                    detected_topics=[],
                    visual_analysis={},
                    sentiment="negative",
                    recommended=False
                )),
            ]
            
            filtered = analyzer.filter_recommended(results)
            
            assert len(filtered) == 1
            assert filtered[0][0] == "/path/1.mp4"
    
    def test_filter_handles_none_results(self):
        """Test that None results are filtered out"""
        with patch('app.core.analyzer.AsyncOpenAI'):
            from app.core.analyzer import VideoAnalyzer, AnalysisResult
            
            analyzer = VideoAnalyzer()
            
            results = [
                ("/path/1.mp4", None),
                ("/path/2.mp4", AnalysisResult(
                    quality_score=0.9,
                    virality_score=0.8,
                    relevance_score=0.9,
                    content_summary="Good",
                    detected_topics=[],
                    visual_analysis={},
                    sentiment="positive",
                    recommended=True
                )),
            ]
            
            filtered = analyzer.filter_recommended(results)
            
            assert len(filtered) == 1
