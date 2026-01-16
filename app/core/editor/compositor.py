"""Video compositor for ranking videos."""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum
import os
import structlog

from app.config import settings

logger = structlog.get_logger()


class TransitionType(Enum):
    """Available transition types."""
    NONE = "none"
    FADE = "fade"
    CROSSFADE = "crossfade"
    SLIDE_LEFT = "slide_left"
    SLIDE_UP = "slide_up"
    ZOOM = "zoom"


class TextPosition(Enum):
    """Text overlay positions."""
    TOP_LEFT = "top_left"
    TOP_CENTER = "top_center"
    TOP_RIGHT = "top_right"
    CENTER = "center"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_CENTER = "bottom_center"
    BOTTOM_RIGHT = "bottom_right"


@dataclass
class TextStyle:
    """Style configuration for text overlays."""
    font: str = "Impact"
    size: int = 60
    color: str = "white"
    stroke_color: str = "black"
    stroke_width: int = 2
    shadow: bool = True
    shadow_offset: Tuple[int, int] = (3, 3)
    background_color: Optional[str] = None
    background_opacity: float = 0.5


@dataclass
class ClipConfig:
    """Configuration for a single clip in the compilation."""
    path: str
    rank: int = 0
    caption: str = ""
    duration: Optional[float] = None  # None = use clip's natural duration
    start_offset: float = 0.0  # Trim from start
    end_offset: float = 0.0  # Trim from end
    volume: float = 0.1  # Low volume for original audio
    show_rank_overlay: bool = True
    show_caption: bool = True
    transition_in: TransitionType = TransitionType.FADE
    transition_out: TransitionType = TransitionType.FADE
    transition_duration: float = 0.5


@dataclass
class CompositorConfig:
    """Configuration for the video compositor."""
    # Output settings
    output_width: int = 1080
    output_height: int = 1920
    fps: int = 30
    codec: str = "libx264"
    audio_codec: str = "aac"
    bitrate: str = "8M"
    
    # Styling
    rank_style: TextStyle = field(default_factory=lambda: TextStyle(
        font="Impact",
        size=120,
        color="yellow"
    ))
    caption_style: TextStyle = field(default_factory=lambda: TextStyle(
        font="Arial",
        size=48,
        color="white"
    ))
    
    # Layout
    rank_position: TextPosition = TextPosition.TOP_RIGHT
    caption_position: TextPosition = TextPosition.BOTTOM_CENTER
    
    # Timing
    max_clip_duration: float = 12.0
    min_clip_duration: float = 3.0
    transition_duration: float = 0.5
    default_transition: TransitionType = TransitionType.CROSSFADE
    
    # Effects
    apply_color_correction: bool = True
    apply_stabilization: bool = False
    apply_watermark: bool = False
    watermark_path: Optional[str] = None


@dataclass
class RenderResult:
    """Result of video rendering."""
    success: bool = False
    output_path: str = ""
    duration_seconds: float = 0.0
    file_size_bytes: int = 0
    resolution: str = ""
    fps: int = 0
    error: str = ""


class VideoCompositor:
    """
    Professional video compositor for ranking videos.
    
    Features:
    - 9:16 vertical format for YouTube Shorts
    - Dynamic text overlays (rank numbers, captions)
    - Smooth transitions between clips
    - Audio mixing and ducking
    - Multiple output quality presets
    """
    
    def __init__(self, config: CompositorConfig = None):
        self.config = config or CompositorConfig()
        
        # Output directory
        self.output_dir = Path(settings.local_storage_path) / "processed"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # MoviePy imports
        self._moviepy = None
    
    @property
    def moviepy(self):
        """Lazy import MoviePy."""
        if self._moviepy is None:
            try:
                import moviepy.editor as mpy
                self._moviepy = mpy
            except ImportError:
                raise ImportError("moviepy is required: pip install moviepy")
        return self._moviepy
    
    def _sanitize_text(self, text: str) -> str:
        """Clean text for safe rendering."""
        if not text:
            return ""
        # Remove emojis and special characters that might crash font rendering
        import re
        return re.sub(r'[^\x00-\x7F]+', '', text)
    
    def _get_position(self, position: TextPosition, text_size: Tuple[int, int]) -> Tuple:
        """Convert TextPosition enum to (x, y) coordinates."""
        w, h = self.config.output_width, self.config.output_height
        tw, th = text_size
        
        margin = 40
        
        positions = {
            TextPosition.TOP_LEFT: (margin, margin),
            TextPosition.TOP_CENTER: ("center", margin),
            TextPosition.TOP_RIGHT: (w - tw - margin, margin),
            TextPosition.CENTER: ("center", "center"),
            TextPosition.BOTTOM_LEFT: (margin, h - th - margin),
            TextPosition.BOTTOM_CENTER: ("center", h - th - margin - 100),
            TextPosition.BOTTOM_RIGHT: (w - tw - margin, h - th - margin),
        }
        
        return positions.get(position, ("center", "center"))
    
    def _create_text_clip(
        self,
        text: str,
        style: TextStyle,
        position: TextPosition,
        duration: float
    ):
        """Create a styled text overlay clip."""
        mpy = self.moviepy
        
        clean_text = self._sanitize_text(text)
        if not clean_text:
            return None
        
        try:
            txt_clip = mpy.TextClip(
                clean_text,
                fontsize=style.size,
                color=style.color,
                font=style.font,
                stroke_color=style.stroke_color,
                stroke_width=style.stroke_width,
                method='caption',
                size=(self.config.output_width - 80, None)  # Max width with margin
            )
            
            # Get text size for positioning
            text_size = txt_clip.size
            pos = self._get_position(position, text_size)
            
            txt_clip = txt_clip.set_position(pos)
            txt_clip = txt_clip.set_duration(duration)
            
            return txt_clip
            
        except Exception as e:
            logger.warning(f"Failed to create text clip: {e}")
            return None
    
    def _process_clip(self, clip_config: ClipConfig) -> Any:
        """
        Process a single video clip.
        
        - Load and validate
        - Resize/crop to 9:16
        - Apply duration limits
        - Add overlays
        """
        mpy = self.moviepy
        
        try:
            # Load clip
            clip = mpy.VideoFileClip(clip_config.path)
            
            # Apply time trimming
            if clip_config.start_offset > 0:
                clip = clip.subclip(clip_config.start_offset)
            if clip_config.end_offset > 0:
                clip = clip.subclip(0, clip.duration - clip_config.end_offset)
            
            # Apply duration limits
            if clip_config.duration:
                target_duration = clip_config.duration
            else:
                target_duration = min(
                    clip.duration,
                    self.config.max_clip_duration
                )
            
            target_duration = max(target_duration, self.config.min_clip_duration)
            
            if clip.duration > target_duration:
                clip = clip.subclip(0, target_duration)
            
            # Resize to target resolution (9:16)
            clip = self._resize_to_vertical(clip)
            
            # Adjust clip audio volume
            if clip.audio:
                clip = clip.volumex(clip_config.volume)
            
            # Create overlays
            overlays = [clip]
            
            # Rank overlay
            if clip_config.show_rank_overlay and clip_config.rank > 0:
                rank_text = f"#{clip_config.rank}"
                rank_clip = self._create_text_clip(
                    rank_text,
                    self.config.rank_style,
                    self.config.rank_position,
                    clip.duration
                )
                if rank_clip:
                    overlays.append(rank_clip)
            
            # Caption overlay
            if clip_config.show_caption and clip_config.caption:
                caption_clip = self._create_text_clip(
                    clip_config.caption,
                    self.config.caption_style,
                    self.config.caption_position,
                    clip.duration
                )
                if caption_clip:
                    overlays.append(caption_clip)
            
            # Composite
            if len(overlays) > 1:
                final_clip = mpy.CompositeVideoClip(
                    overlays,
                    size=(self.config.output_width, self.config.output_height)
                )
            else:
                final_clip = clip
            
            return final_clip
            
        except Exception as e:
            logger.error(f"Failed to process clip {clip_config.path}: {e}")
            return None
    
    def _resize_to_vertical(self, clip) -> Any:
        """Resize clip to 9:16 aspect ratio."""
        mpy = self.moviepy
        
        w, h = clip.size
        target_w = self.config.output_width
        target_h = self.config.output_height
        target_ratio = target_h / target_w
        
        current_ratio = h / w
        
        if abs(current_ratio - target_ratio) < 0.1:
            # Already close to 9:16
            return clip.resize((target_w, target_h))
        
        if current_ratio < target_ratio:
            # Video is more horizontal - crop sides
            new_w = int(h / target_ratio)
            x_center = w // 2
            clip = mpy.vfx.crop(
                clip,
                x1=x_center - new_w // 2,
                x2=x_center + new_w // 2,
                y1=0,
                y2=h
            )
        else:
            # Video is more vertical than needed - crop top/bottom
            new_h = int(w * target_ratio)
            y_center = h // 2
            clip = mpy.vfx.crop(
                clip,
                x1=0,
                x2=w,
                y1=y_center - new_h // 2,
                y2=y_center + new_h // 2
            )
        
        return clip.resize((target_w, target_h))
    
    def _apply_transition(
        self,
        clip1,
        clip2,
        transition_type: TransitionType,
        duration: float
    ):
        """Apply transition between two clips."""
        mpy = self.moviepy
        
        if transition_type == TransitionType.NONE:
            return mpy.concatenate_videoclips([clip1, clip2])
        
        if transition_type == TransitionType.FADE:
            clip1 = clip1.fadeout(duration)
            clip2 = clip2.fadein(duration)
            return mpy.concatenate_videoclips([clip1, clip2])
        
        if transition_type == TransitionType.CROSSFADE:
            return mpy.concatenate_videoclips(
                [clip1, clip2],
                method="compose",
                padding=-duration
            )
        
        # Default: just concatenate
        return mpy.concatenate_videoclips([clip1, clip2])
    
    def render_ranking_video(
        self,
        clips: List[ClipConfig],
        output_filename: str,
        title: str = None,
        audio_track: str = None
    ) -> RenderResult:
        """
        Render a complete ranking video.
        
        Args:
            clips: List of ClipConfig objects (in ranking order, countdown)
            output_filename: Output filename
            title: Optional title card text
            audio_track: Optional path to mixed audio track
            
        Returns:
            RenderResult with output info
        """
        result = RenderResult()
        mpy = self.moviepy
        
        if not clips:
            result.error = "No clips to render"
            return result
        
        try:
            logger.info(f"Starting render: {len(clips)} clips")
            
            processed_clips = []
            
            # Process each clip
            for i, clip_config in enumerate(clips):
                logger.debug(f"Processing clip {i+1}/{len(clips)}")
                
                processed = self._process_clip(clip_config)
                if processed:
                    processed_clips.append(processed)
            
            if not processed_clips:
                result.error = "No clips successfully processed"
                return result
            
            # Concatenate with transitions
            if len(processed_clips) == 1:
                final_video = processed_clips[0]
            else:
                final_video = mpy.concatenate_videoclips(
                    processed_clips,
                    method="compose"
                )
            
            # Replace audio if provided
            if audio_track and os.path.exists(audio_track):
                try:
                    new_audio = mpy.AudioFileClip(audio_track)
                    # Trim audio to match video
                    if new_audio.duration > final_video.duration:
                        new_audio = new_audio.subclip(0, final_video.duration)
                    final_video = final_video.set_audio(new_audio)
                except Exception as e:
                    logger.warning(f"Failed to set audio track: {e}")
            
            # Set output path
            output_path = str(self.output_dir / output_filename)
            
            # Render
            logger.info("Writing video file...")
            
            final_video.write_videofile(
                output_path,
                fps=self.config.fps,
                codec=self.config.codec,
                audio_codec=self.config.audio_codec,
                bitrate=self.config.bitrate,
                threads=4,
                preset="medium",
                verbose=False,
                logger=None
            )
            
            # Close clips
            for clip in processed_clips:
                clip.close()
            final_video.close()
            
            # Get file info
            result.success = True
            result.output_path = output_path
            result.duration_seconds = final_video.duration
            result.file_size_bytes = os.path.getsize(output_path)
            result.resolution = f"{self.config.output_width}x{self.config.output_height}"
            result.fps = self.config.fps
            
            logger.info(
                "Render complete",
                output=output_path,
                duration=result.duration_seconds,
                size_mb=result.file_size_bytes / (1024 * 1024)
            )
            
        except Exception as e:
            logger.error(f"Rendering failed: {e}")
            result.error = str(e)
        
        return result
    
    def create_title_card(
        self,
        text: str,
        duration: float = 3.0,
        background_color: str = "black"
    ):
        """Create a title card clip."""
        mpy = self.moviepy
        
        # Create background
        bg = mpy.ColorClip(
            size=(self.config.output_width, self.config.output_height),
            color=self._parse_color(background_color),
            duration=duration
        )
        
        # Create title text
        title_style = TextStyle(
            font="Impact",
            size=80,
            color="white"
        )
        
        title = self._create_text_clip(
            text,
            title_style,
            TextPosition.CENTER,
            duration
        )
        
        if title:
            return mpy.CompositeVideoClip([bg, title])
        return bg
    
    def _parse_color(self, color: str) -> Tuple[int, int, int]:
        """Parse color string to RGB tuple."""
        colors = {
            "black": (0, 0, 0),
            "white": (255, 255, 255),
            "red": (255, 0, 0),
            "green": (0, 255, 0),
            "blue": (0, 0, 255),
            "yellow": (255, 255, 0),
        }
        return colors.get(color.lower(), (0, 0, 0))
    
    def get_render_preview(
        self,
        clips: List[ClipConfig],
        frame_time: float = 2.0
    ) -> str:
        """Generate a preview frame from the first clip."""
        if not clips:
            return ""
        
        try:
            mpy = self.moviepy
            clip = mpy.VideoFileClip(clips[0].path)
            
            # Get frame at specified time
            frame = clip.get_frame(min(frame_time, clip.duration - 0.1))
            
            preview_path = str(self.output_dir / "preview.jpg")
            
            from PIL import Image
            img = Image.fromarray(frame)
            img.save(preview_path)
            
            clip.close()
            return preview_path
            
        except Exception as e:
            logger.error(f"Preview generation failed: {e}")
            return ""
