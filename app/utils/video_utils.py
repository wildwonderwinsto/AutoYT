"""Video processing utility functions"""

from typing import Dict, Any, Optional, Tuple
from pathlib import Path
import subprocess
import json
import structlog

logger = structlog.get_logger()


def get_video_info(video_path: str) -> Optional[Dict[str, Any]]:
    """
    Get detailed video information using ffprobe.
    
    Returns metadata like duration, resolution, codec, etc.
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            video_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            logger.error("ffprobe failed", path=video_path, error=result.stderr)
            return None
        
        data = json.loads(result.stdout)
        
        # Extract relevant info
        video_stream = None
        audio_stream = None
        
        for stream in data.get("streams", []):
            if stream["codec_type"] == "video" and not video_stream:
                video_stream = stream
            elif stream["codec_type"] == "audio" and not audio_stream:
                audio_stream = stream
        
        format_info = data.get("format", {})
        
        return {
            "duration": float(format_info.get("duration", 0)),
            "size_bytes": int(format_info.get("size", 0)),
            "bit_rate": int(format_info.get("bit_rate", 0)),
            "format": format_info.get("format_name"),
            "width": video_stream.get("width") if video_stream else None,
            "height": video_stream.get("height") if video_stream else None,
            "fps": eval(video_stream.get("r_frame_rate", "0/1")) if video_stream else None,
            "video_codec": video_stream.get("codec_name") if video_stream else None,
            "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
            "has_audio": audio_stream is not None
        }
        
    except subprocess.TimeoutExpired:
        logger.error("ffprobe timed out", path=video_path)
        return None
    except Exception as e:
        logger.error("Failed to get video info", path=video_path, error=str(e))
        return None


def extract_audio(
    video_path: str,
    output_path: str = None,
    format: str = "mp3"
) -> Optional[str]:
    """
    Extract audio from a video file.
    
    Returns the path to the extracted audio file.
    """
    if output_path is None:
        base = Path(video_path).stem
        output_path = str(Path(video_path).parent / f"{base}.{format}")
    
    try:
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-vn",  # No video
            "-acodec", "libmp3lame" if format == "mp3" else "aac",
            "-y",  # Overwrite
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode != 0:
            logger.error("Audio extraction failed", error=result.stderr)
            return None
        
        return output_path
        
    except Exception as e:
        logger.error("Failed to extract audio", path=video_path, error=str(e))
        return None


def resize_video(
    video_path: str,
    output_path: str,
    width: int = None,
    height: int = None,
    maintain_aspect: bool = True
) -> Optional[str]:
    """
    Resize a video to specified dimensions.
    
    If maintain_aspect is True, the video will be padded to fit the target size.
    """
    if width is None and height is None:
        raise ValueError("Must specify at least width or height")
    
    try:
        # Build filter
        if maintain_aspect:
            if width and height:
                scale_filter = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
            elif width:
                scale_filter = f"scale={width}:-2"
            else:
                scale_filter = f"scale=-2:{height}"
        else:
            scale_filter = f"scale={width or -2}:{height or -2}"
        
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-vf", scale_filter,
            "-c:a", "copy",
            "-y",
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode != 0:
            logger.error("Resize failed", error=result.stderr)
            return None
        
        return output_path
        
    except Exception as e:
        logger.error("Failed to resize video", path=video_path, error=str(e))
        return None


def convert_to_vertical(
    video_path: str,
    output_path: str,
    target_width: int = 1080,
    target_height: int = 1920
) -> Optional[str]:
    """
    Convert a video to vertical format (9:16) for Shorts.
    
    Handles both horizontal and vertical source videos.
    """
    info = get_video_info(video_path)
    if not info:
        return None
    
    source_width = info.get("width", 0)
    source_height = info.get("height", 0)
    
    if source_width == 0 or source_height == 0:
        return None
    
    try:
        if source_width > source_height:
            # Horizontal video - crop to center
            crop_width = int(source_height * 9 / 16)
            crop_x = (source_width - crop_width) // 2
            filter_str = f"crop={crop_width}:{source_height}:{crop_x}:0,scale={target_width}:{target_height}"
        else:
            # Already vertical - just scale
            filter_str = f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black"
        
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-vf", filter_str,
            "-c:a", "aac",
            "-y",
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode != 0:
            logger.error("Vertical conversion failed", error=result.stderr)
            return None
        
        return output_path
        
    except Exception as e:
        logger.error("Failed to convert to vertical", path=video_path, error=str(e))
        return None


def trim_video(
    video_path: str,
    output_path: str,
    start_time: float,
    end_time: float
) -> Optional[str]:
    """
    Trim a video to a specific time range.
    """
    try:
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-ss", str(start_time),
            "-to", str(end_time),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-y",
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode != 0:
            logger.error("Trim failed", error=result.stderr)
            return None
        
        return output_path
        
    except Exception as e:
        logger.error("Failed to trim video", path=video_path, error=str(e))
        return None


def create_thumbnail(
    video_path: str,
    output_path: str,
    time_offset: float = 1.0,
    width: int = 720,
    height: int = 1280
) -> Optional[str]:
    """
    Create a thumbnail image from a video frame.
    """
    try:
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-ss", str(time_offset),
            "-vframes", "1",
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black",
            "-y",
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            logger.error("Thumbnail creation failed", error=result.stderr)
            return None
        
        return output_path
        
    except Exception as e:
        logger.error("Failed to create thumbnail", path=video_path, error=str(e))
        return None


def get_video_duration(video_path: str) -> Optional[float]:
    """Get video duration in seconds."""
    info = get_video_info(video_path)
    return info.get("duration") if info else None


def concatenate_videos(
    video_paths: list,
    output_path: str
) -> Optional[str]:
    """
    Concatenate multiple videos into one.
    
    All videos should have the same resolution and codec.
    """
    if not video_paths:
        return None
    
    try:
        # Create a temporary file list
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            for path in video_paths:
                f.write(f"file '{path}'\n")
            list_file = f.name
        
        cmd = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            "-y",
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600
        )
        
        # Cleanup
        Path(list_file).unlink(missing_ok=True)
        
        if result.returncode != 0:
            logger.error("Concatenation failed", error=result.stderr)
            return None
        
        return output_path
        
    except Exception as e:
        logger.error("Failed to concatenate videos", error=str(e))
        return None
