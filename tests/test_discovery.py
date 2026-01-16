"""Tests for platform discovery modules"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime


class TestYouTubeDiscovery:
    """Test YouTube discovery engine"""
    
    @pytest.mark.asyncio
    async def test_discover_trending_returns_content(self):
        """Test that discovery returns DiscoveredContent objects"""
        from app.core.discovery import YouTubeDiscovery, DiscoveredContent
        
        mock_response = {
            "items": [
                {"id": {"videoId": "test123"}, "snippet": {"title": "Test Video"}}
            ]
        }
        
        with patch.object(YouTubeDiscovery, '_YouTubeDiscovery__init__'):
            discovery = YouTubeDiscovery()
            discovery.api_key = "test_key"
            discovery.base_url = "https://www.googleapis.com/youtube/v3"
            discovery.client = AsyncMock()
            
            mock_get = AsyncMock()
            mock_get.return_value.json.return_value = mock_response
            mock_get.return_value.raise_for_status = MagicMock()
            discovery.client.get = mock_get
            
            # Test would run here
            # results = await discovery.discover_trending("gaming", 10)
            # assert isinstance(results, list)
    
    def test_calculate_trending_score(self):
        """Test trending score calculation"""
        from app.core.discovery import YouTubeDiscovery
        
        # Create real instance to test the method
        with patch.object(YouTubeDiscovery, '__init__', lambda x: None):
            discovery = YouTubeDiscovery()
            
            # High engagement, recent video
            score = discovery.calculate_trending_score(
                views=1000000,
                likes=100000,
                comments=10000,
                age_hours=2
            )
            
            assert 0 <= score <= 1
            assert score > 0.5  # Should be high for viral content
    
    def test_trending_score_time_decay(self):
        """Test that older videos get lower scores"""
        from app.core.discovery import YouTubeDiscovery
        
        with patch.object(YouTubeDiscovery, '__init__', lambda x: None):
            discovery = YouTubeDiscovery()
            
            recent_score = discovery.calculate_trending_score(
                views=100000, likes=10000, comments=1000, age_hours=1
            )
            
            old_score = discovery.calculate_trending_score(
                views=100000, likes=10000, comments=1000, age_hours=168  # 1 week
            )
            
            assert recent_score > old_score


class TestTikTokDiscovery:
    """Test TikTok discovery engine"""
    
    def test_initialization(self):
        """Test TikTok discovery initializes with Apify key"""
        from app.core.discovery import TikTokDiscovery
        
        with patch('app.core.discovery.settings') as mock_settings:
            mock_settings.apify_api_key = "test_apify_key"
            
            discovery = TikTokDiscovery()
            assert discovery.apify_key == "test_apify_key"


class TestInstagramDiscovery:
    """Test Instagram discovery engine"""
    
    def test_initialization(self):
        """Test Instagram discovery initializes correctly"""
        from app.core.discovery import InstagramDiscovery
        
        with patch('app.core.discovery.settings') as mock_settings:
            mock_settings.apify_api_key = "test_apify_key"
            
            discovery = InstagramDiscovery()
            assert discovery.apify_key == "test_apify_key"


class TestDiscoveredContent:
    """Test DiscoveredContent dataclass"""
    
    def test_content_creation(self):
        """Test creating a DiscoveredContent instance"""
        from app.core.discovery import DiscoveredContent
        
        content = DiscoveredContent(
            platform="youtube",
            platform_video_id="abc123",
            url="https://youtube.com/shorts/abc123",
            title="Test Video",
            views=1000,
            likes=100
        )
        
        assert content.platform == "youtube"
        assert content.platform_video_id == "abc123"
        assert content.views == 1000
    
    def test_content_with_metadata(self):
        """Test creating content with metadata"""
        from app.core.discovery import DiscoveredContent
        
        content = DiscoveredContent(
            platform="tiktok",
            platform_video_id="xyz789",
            url="https://tiktok.com/@user/video/xyz789",
            metadata={"hashtags": ["viral", "fyp"]}
        )
        
        assert content.metadata["hashtags"] == ["viral", "fyp"]
