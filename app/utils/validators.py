"""Input validation utilities"""

import re
from typing import Optional, List
from urllib.parse import urlparse

from app.config import settings


def validate_url(url: str) -> bool:
    """
    Validate that a URL is well-formed and points to a supported platform.
    """
    if not url:
        return False
    
    try:
        parsed = urlparse(url)
        
        # Check for valid scheme
        if parsed.scheme not in ("http", "https"):
            return False
        
        # Check for valid netloc
        if not parsed.netloc:
            return False
        
        # Supported platforms
        supported_domains = [
            "youtube.com",
            "www.youtube.com",
            "youtu.be",
            "tiktok.com",
            "www.tiktok.com",
            "vm.tiktok.com",
            "instagram.com",
            "www.instagram.com",
            "snapchat.com",
            "www.snapchat.com",
            "story.snapchat.com"
        ]
        
        # Check if domain is supported
        domain = parsed.netloc.lower()
        return any(d in domain for d in supported_domains)
        
    except Exception:
        return False


def validate_video_format(format: str) -> bool:
    """
    Validate that a video format is supported.
    """
    return format.lower() in settings.supported_formats


def validate_resolution(resolution: str) -> bool:
    """
    Validate that a resolution string is valid.
    
    Accepts formats: "1080", "720", "1080x1920", "1920x1080"
    """
    single_pattern = r"^\d{3,4}$"
    full_pattern = r"^\d{3,4}x\d{3,4}$"
    
    return bool(
        re.match(single_pattern, resolution) or
        re.match(full_pattern, resolution)
    )


def validate_timeframe(timeframe: str) -> bool:
    """
    Validate that a timeframe string is valid.
    """
    valid_timeframes = ["1h", "6h", "12h", "24h", "7d", "30d"]
    return timeframe.lower() in valid_timeframes


def validate_platform(platform: str) -> bool:
    """
    Validate that a platform name is supported.
    """
    valid_platforms = ["youtube", "tiktok", "instagram", "snapchat"]
    return platform.lower() in valid_platforms


def validate_niche(niche: str) -> bool:
    """
    Validate that a niche string is acceptable.
    
    Checks for length and disallowed characters.
    """
    if not niche or len(niche) < 1 or len(niche) > 100:
        return False
    
    # Disallow special characters that could cause issues
    disallowed = ["<", ">", "{", "}", "[", "]", "\\", "^", "`"]
    return not any(char in niche for char in disallowed)


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename to remove problematic characters.
    """
    # Remove or replace problematic characters
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
    sanitized = re.sub(r'\s+', '_', sanitized)
    sanitized = re.sub(r'_+', '_', sanitized)
    sanitized = sanitized.strip('_')
    
    # Limit length
    if len(sanitized) > 200:
        sanitized = sanitized[:200]
    
    return sanitized


def extract_platform_from_url(url: str) -> Optional[str]:
    """
    Extract the platform name from a video URL.
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        if "youtube" in domain or "youtu.be" in domain:
            return "youtube"
        elif "tiktok" in domain:
            return "tiktok"
        elif "instagram" in domain:
            return "instagram"
        elif "snapchat" in domain:
            return "snapchat"
        
        return None
        
    except Exception:
        return None


def extract_video_id_from_url(url: str) -> Optional[str]:
    """
    Extract the video ID from a platform URL.
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        path = parsed.path
        query = parsed.query
        
        if "youtube" in domain:
            # youtube.com/watch?v=VIDEO_ID
            if "v=" in query:
                match = re.search(r'v=([^&]+)', query)
                return match.group(1) if match else None
            # youtube.com/shorts/VIDEO_ID
            elif "/shorts/" in path:
                return path.split("/shorts/")[1].split("/")[0]
        
        elif "youtu.be" in domain:
            # youtu.be/VIDEO_ID
            return path.strip("/").split("/")[0]
        
        elif "tiktok" in domain:
            # tiktok.com/@user/video/VIDEO_ID
            match = re.search(r'/video/(\d+)', path)
            return match.group(1) if match else None
        
        elif "instagram" in domain:
            # instagram.com/reel/VIDEO_ID or /p/VIDEO_ID
            match = re.search(r'/(reel|p)/([^/]+)', path)
            return match.group(2) if match else None
        
        return None
        
    except Exception:
        return None


def validate_job_config(config: dict) -> List[str]:
    """
    Validate a job configuration dictionary.
    
    Returns a list of error messages (empty if valid).
    """
    errors = []
    
    # Required fields
    if "niche" not in config:
        errors.append("niche is required")
    elif not validate_niche(config["niche"]):
        errors.append("niche is invalid")
    
    # Platform validation
    if "platforms" in config:
        for platform in config["platforms"]:
            if not validate_platform(platform):
                errors.append(f"Invalid platform: {platform}")
    
    # Timeframe validation
    if "timeframe" in config:
        if not validate_timeframe(config["timeframe"]):
            errors.append(f"Invalid timeframe: {config['timeframe']}")
    
    # Score thresholds
    for field in ["min_quality_score", "min_virality_score", "min_relevance_score"]:
        if field in config:
            value = config[field]
            if not isinstance(value, (int, float)) or value < 0 or value > 1:
                errors.append(f"{field} must be between 0 and 1")
    
    # Max videos
    if "max_videos" in config:
        max_videos = config["max_videos"]
        if not isinstance(max_videos, int) or max_videos < 10 or max_videos > 500:
            errors.append("max_videos must be between 10 and 500")
    
    return errors
