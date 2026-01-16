"""Discovery module for multi-platform content sourcing."""

from app.core.discovery.base_client import BasePlatformClient
from app.core.discovery.youtube_client import YouTubeClient
from app.core.discovery.social_client import ApifySocialClient
from app.core.discovery.orchestrator import DiscoveryOrchestrator

__all__ = [
    "BasePlatformClient",
    "YouTubeClient",
    "ApifySocialClient",
    "DiscoveryOrchestrator"
]
