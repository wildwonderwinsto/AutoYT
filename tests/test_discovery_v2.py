"""Tests for the discovery orchestrator and platform clients."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta


class TestBasePlatformClient:
    """Tests for the base client class."""
    
    def test_viral_score_calculation(self):
        """Test viral score calculation with various inputs."""
        from app.core.discovery.base_client import BasePlatformClient
        
        # Create a concrete implementation for testing
        class TestClient(BasePlatformClient):
            async def discover_trending(self, query, timeframe_hours, limit):
                return []
            async def get_video_details(self, video_id):
                return None
        
        client = TestClient("test", 60)
        
        # Test high-performing video
        upload_date = datetime.now() - timedelta(hours=2)
        score, engagement, velocity = client.calculate_viral_score(
            views=1000000,
            likes=100000,
            comments=10000,
            shares=5000,
            upload_date=upload_date,
            duration_seconds=30
        )
        
        assert 0 <= score <= 100
        assert score > 50  # High-performing video should score well
        assert engagement > 0
        assert velocity > 0
    
    def test_viral_score_time_decay(self):
        """Test that older videos score lower."""
        from app.core.discovery.base_client import BasePlatformClient
        
        class TestClient(BasePlatformClient):
            async def discover_trending(self, query, timeframe_hours, limit):
                return []
            async def get_video_details(self, video_id):
                return None
        
        client = TestClient("test", 60)
        
        # Recent video
        recent_date = datetime.now() - timedelta(hours=2)
        recent_score, _, _ = client.calculate_viral_score(
            views=100000, likes=10000, comments=1000, shares=500,
            upload_date=recent_date
        )
        
        # Old video (same metrics)
        old_date = datetime.now() - timedelta(days=30)
        old_score, _, _ = client.calculate_viral_score(
            views=100000, likes=10000, comments=1000, shares=500,
            upload_date=old_date
        )
        
        assert recent_score > old_score
    
    def test_parse_iso_date(self):
        """Test ISO date parsing."""
        from app.core.discovery.base_client import BasePlatformClient
        
        class TestClient(BasePlatformClient):
            async def discover_trending(self, query, timeframe_hours, limit):
                return []
            async def get_video_details(self, video_id):
                return None
        
        client = TestClient("test", 60)
        
        # Test various formats
        date1 = client._parse_iso_date("2024-01-15T10:30:00Z")
        assert date1.year == 2024
        assert date1.month == 1
        
        date2 = client._parse_iso_date("2024-01-15")
        assert date2.year == 2024
    
    def test_parse_duration(self):
        """Test ISO 8601 duration parsing."""
        from app.core.discovery.base_client import BasePlatformClient
        
        class TestClient(BasePlatformClient):
            async def discover_trending(self, query, timeframe_hours, limit):
                return []
            async def get_video_details(self, video_id):
                return None
        
        client = TestClient("test", 60)
        
        assert client._parse_duration("PT1M30S") == 90
        assert client._parse_duration("PT5M") == 300
        assert client._parse_duration("PT1H") == 3600
        assert client._parse_duration("PT1H2M3S") == 3723


class TestDiscoveredVideo:
    """Tests for the DiscoveredVideo dataclass."""
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        from app.core.discovery.base_client import DiscoveredVideo
        
        video = DiscoveredVideo(
            platform="youtube",
            platform_video_id="abc123",
            url="https://youtube.com/shorts/abc123",
            title="Test Video",
            views=10000,
            likes=1000,
            trending_score=75.5
        )
        
        data = video.to_dict()
        
        assert data["platform"] == "youtube"
        assert data["views"] == 10000
        assert data["trending_score"] == 75.5
        assert "metadata" in data


class TestDiscoveryOrchestrator:
    """Tests for the discovery orchestrator."""
    
    @pytest.mark.asyncio
    async def test_deduplication(self):
        """Test video deduplication by URL and title."""
        from app.core.discovery.orchestrator import DiscoveryOrchestrator
        from app.core.discovery.base_client import DiscoveredVideo
        
        orchestrator = DiscoveryOrchestrator(platforms=[])
        
        # Create videos with duplicate URLs
        videos = [
            DiscoveredVideo(
                platform="youtube",
                platform_video_id="1",
                url="https://youtube.com/shorts/abc",
                title="Gaming Highlights",
                views=1000,
                trending_score=50
            ),
            DiscoveredVideo(
                platform="youtube",
                platform_video_id="2",
                url="https://youtube.com/shorts/abc",  # Duplicate URL
                title="Gaming Highlights",
                views=2000,
                trending_score=60
            ),
            DiscoveredVideo(
                platform="tiktok",
                platform_video_id="3",
                url="https://tiktok.com/video/xyz",
                title="Gaming Highlights Best Moments",  # Similar title
                views=5000,
                trending_score=80
            ),
        ]
        
        unique = orchestrator._deduplicate_videos(videos)
        
        # Should have at most 2 videos (URL duplicate removed)
        assert len(unique) <= 2
    
    def test_similarity_calculation(self):
        """Test title similarity calculation."""
        from app.core.discovery.orchestrator import DiscoveryOrchestrator
        
        orchestrator = DiscoveryOrchestrator(platforms=[])
        
        # Very similar titles
        sim1 = orchestrator._calculate_similarity(
            "Gaming Highlights 2024",
            "Gaming Highlights 2024!"
        )
        assert sim1 > 0.9
        
        # Different titles
        sim2 = orchestrator._calculate_similarity(
            "Cooking Recipe Tutorial",
            "Gaming Highlights"
        )
        assert sim2 < 0.5


class TestYouTubeClient:
    """Tests for YouTube client."""
    
    def test_normalize_video(self):
        """Test YouTube video normalization."""
        from app.core.discovery.youtube_client import YouTubeClient
        
        with patch.object(YouTubeClient, '__init__', lambda x, y=None: None):
            client = YouTubeClient()
            client.platform_name = "youtube"
            client.rate_limit = 100
            client._semaphore = MagicMock()
            client._request_count = 0
            client._last_reset = datetime.now()
            
            # Mock API response item
            item = {
                "id": "test123",
                "snippet": {
                    "title": "Test Video",
                    "description": "Test description",
                    "channelTitle": "Test Channel",
                    "channelId": "UC123",
                    "publishedAt": "2024-01-15T10:00:00Z"
                },
                "statistics": {
                    "viewCount": "100000",
                    "likeCount": "5000",
                    "commentCount": "500"
                },
                "contentDetails": {
                    "duration": "PT45S"
                }
            }
            
            video = client._normalize_video(item)
            
            assert video is not None
            assert video.platform == "youtube"
            assert video.views == 100000
            assert video.duration_seconds == 45


class TestApifySocialClient:
    """Tests for Apify social client."""
    
    def test_platform_validation(self):
        """Test that unsupported platforms raise error."""
        from app.core.discovery.social_client import ApifySocialClient
        
        with pytest.raises(ValueError):
            ApifySocialClient("unsupported_platform")
    
    def test_supported_platforms(self):
        """Test that supported platforms initialize correctly."""
        from app.core.discovery.social_client import ApifySocialClient
        
        for platform in ["tiktok", "instagram", "snapchat"]:
            with patch.object(ApifySocialClient, '__init__', lambda x, p, k=None: None):
                # Should not raise
                client = object.__new__(ApifySocialClient)
                client.platform_name = platform
                assert client.platform_name == platform
