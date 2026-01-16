"""Core business logic package"""

from app.core.database import engine, Base, get_db

# Discovery
from app.core.discovery import (
    DiscoveryOrchestrator,
    YouTubeClient,
    ApifySocialClient,
    BasePlatformClient
)

# Analysis
from app.core.analyzer import VisionAnalyzer, QualityChecker, WatermarkDetector
from app.core.selector import ContentSelector, SelectionConfig
from app.core.downloader import VideoDownloader

# Audio
from app.core.audio import TTSService, AudioMixer

# Editor
from app.core.editor import VideoCompositor, EffectsEngine, TextRenderer

__all__ = [
    # Database
    "engine",
    "Base",
    "get_db",
    # Discovery
    "DiscoveryOrchestrator",
    "YouTubeClient",
    "ApifySocialClient",
    "BasePlatformClient",
    # Analysis
    "VisionAnalyzer",
    "QualityChecker",
    "WatermarkDetector",
    "ContentSelector",
    "SelectionConfig",
    "VideoDownloader",
    # Audio
    "TTSService",
    "AudioMixer",
    # Editor
    "VideoCompositor",
    "EffectsEngine",
    "TextRenderer"
]
