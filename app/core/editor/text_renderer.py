"""Text rendering utilities for video overlays."""

from typing import Tuple, Optional, Dict, Any, List
from dataclasses import dataclass
from pathlib import Path
from enum import Enum
import structlog

logger = structlog.get_logger()


class AnimationType(Enum):
    """Text animation types."""
    NONE = "none"
    FADE_IN = "fade_in"
    SLIDE_UP = "slide_up"
    SLIDE_LEFT = "slide_left"
    TYPEWRITER = "typewriter"
    BOUNCE = "bounce"
    SCALE_IN = "scale_in"


@dataclass
class TextConfig:
    """Configuration for text rendering."""
    text: str
    font: str = "Impact"
    size: int = 48
    color: str = "white"
    stroke_color: str = "black"
    stroke_width: int = 2
    position: Tuple = ("center", "center")
    align: str = "center"
    duration: float = 3.0
    start_time: float = 0.0
    animation_in: AnimationType = AnimationType.FADE_IN
    animation_out: AnimationType = AnimationType.FADE_IN
    animation_duration: float = 0.3
    shadow: bool = True
    shadow_color: str = "black"
    shadow_offset: Tuple[int, int] = (2, 2)
    background: bool = False
    background_color: str = "black"
    background_opacity: float = 0.5
    background_padding: int = 10


class TextRenderer:
    """
    Advanced text rendering for video overlays.
    
    Features:
    - Multiple fonts and styles
    - Animations (fade, slide, typewriter)
    - Drop shadows
    - Background boxes
    - Word-by-word animation
    """
    
    # Common fonts that should be available
    FALLBACK_FONTS = ["Arial", "Helvetica", "DejaVu Sans", "Liberation Sans"]
    
    def __init__(self):
        self._moviepy = None
        self._pillow = None
    
    @property
    def moviepy(self):
        if self._moviepy is None:
            import moviepy.editor as mpy
            self._moviepy = mpy
        return self._moviepy
    
    @property
    def pillow(self):
        if self._pillow is None:
            from PIL import Image, ImageDraw, ImageFont
            self._pillow = {"Image": Image, "ImageDraw": ImageDraw, "ImageFont": ImageFont}
        return self._pillow
    
    def _find_font(self, font_name: str, size: int):
        """Find a working font, with fallbacks."""
        ImageFont = self.pillow["ImageFont"]
        
        # Try exact font name
        fonts_to_try = [font_name] + self.FALLBACK_FONTS
        
        for font in fonts_to_try:
            try:
                # Try as path first
                if Path(font).exists():
                    return ImageFont.truetype(font, size)
                
                # Try as system font
                return ImageFont.truetype(font, size)
            except Exception:
                continue
        
        # Fall back to default
        return ImageFont.load_default()
    
    def create_text_clip(self, config: TextConfig):
        """Create a MoviePy text clip with styling."""
        mpy = self.moviepy
        
        try:
            txt_clip = mpy.TextClip(
                config.text,
                fontsize=config.size,
                color=config.color,
                font=config.font,
                stroke_color=config.stroke_color,
                stroke_width=config.stroke_width,
                align=config.align,
                method="caption" if len(config.text) > 50 else "label"
            )
            
            txt_clip = txt_clip.set_position(config.position)
            txt_clip = txt_clip.set_start(config.start_time)
            txt_clip = txt_clip.set_duration(config.duration)
            
            # Apply animations
            if config.animation_in != AnimationType.NONE:
                txt_clip = self._apply_animation_in(txt_clip, config)
            
            if config.animation_out != AnimationType.NONE:
                txt_clip = self._apply_animation_out(txt_clip, config)
            
            return txt_clip
            
        except Exception as e:
            logger.error(f"Failed to create text clip: {e}")
            return None
    
    def _apply_animation_in(self, clip, config: TextConfig):
        """Apply entrance animation."""
        duration = config.animation_duration
        
        if config.animation_in == AnimationType.FADE_IN:
            return clip.crossfadein(duration)
        
        if config.animation_in == AnimationType.SLIDE_UP:
            # Start from below
            original_pos = config.position
            
            def position_func(t):
                if t < duration:
                    progress = t / duration
                    offset = (1 - progress) * 100
                    if isinstance(original_pos[1], str):
                        return (original_pos[0], ("center", offset))
                    return (original_pos[0], original_pos[1] + offset)
                return original_pos
            
            return clip.set_position(position_func)
        
        if config.animation_in == AnimationType.SCALE_IN:
            def resize_func(t):
                if t < duration:
                    return 0.1 + 0.9 * (t / duration)
                return 1.0
            
            return clip.resize(resize_func)
        
        return clip.crossfadein(duration)
    
    def _apply_animation_out(self, clip, config: TextConfig):
        """Apply exit animation."""
        duration = config.animation_duration
        
        if config.animation_out == AnimationType.FADE_IN:  # Fade out
            return clip.crossfadeout(duration)
        
        return clip.crossfadeout(duration)
    
    def create_animated_counter(
        self,
        start_num: int,
        end_num: int,
        duration: float,
        style: dict = None
    ) -> List:
        """Create animated counting number clips."""
        mpy = self.moviepy
        
        style = style or {
            "font": "Impact",
            "size": 120,
            "color": "yellow",
            "stroke_color": "black",
            "stroke_width": 3
        }
        
        clips = []
        step = 1 if end_num > start_num else -1
        numbers = list(range(start_num, end_num + step, step))
        time_per_number = duration / len(numbers)
        
        for i, num in enumerate(numbers):
            clip = mpy.TextClip(
                str(num),
                fontsize=style["size"],
                color=style["color"],
                font=style["font"],
                stroke_color=style["stroke_color"],
                stroke_width=style["stroke_width"]
            )
            
            clip = clip.set_position("center")
            clip = clip.set_start(i * time_per_number)
            clip = clip.set_duration(time_per_number)
            
            clips.append(clip)
        
        return clips
    
    def create_lower_third(
        self,
        name: str,
        title: str = "",
        duration: float = 4.0,
        width: int = 800,
        height: int = 100
    ):
        """Create a lower-third graphic with name and title."""
        mpy = self.moviepy
        
        clips = []
        
        # Background bar
        bar = mpy.ColorClip(
            size=(width, height),
            color=(20, 20, 20)
        ).set_opacity(0.8).set_duration(duration)
        
        bar = bar.crossfadein(0.3).crossfadeout(0.3)
        clips.append(bar)
        
        # Name
        name_clip = mpy.TextClip(
            name,
            fontsize=36,
            color="white",
            font="Arial Bold"
        ).set_duration(duration)
        
        name_clip = name_clip.set_position((20, 10))
        clips.append(name_clip)
        
        # Title
        if title:
            title_clip = mpy.TextClip(
                title,
                fontsize=24,
                color="gray"
            ).set_duration(duration)
            
            title_clip = title_clip.set_position((20, 55))
            clips.append(title_clip)
        
        # Composite
        lower_third = mpy.CompositeVideoClip(clips, size=(width, height))
        
        return lower_third
    
    def create_caption_track(
        self,
        captions: List[Dict[str, Any]],
        style: dict = None
    ) -> List:
        """
        Create caption clips from timed text segments.
        
        captions: List of {"text": str, "start": float, "end": float}
        """
        style = style or {
            "font": "Arial",
            "size": 42,
            "color": "white",
            "stroke_width": 2,
            "position": ("center", 0.85)  # Relative position
        }
        
        clips = []
        
        for caption in captions:
            config = TextConfig(
                text=caption["text"],
                font=style["font"],
                size=style["size"],
                color=style["color"],
                stroke_width=style.get("stroke_width", 2),
                position=style["position"],
                start_time=caption["start"],
                duration=caption["end"] - caption["start"],
                animation_in=AnimationType.FADE_IN,
                animation_out=AnimationType.FADE_IN,
                animation_duration=0.15
            )
            
            clip = self.create_text_clip(config)
            if clip:
                clips.append(clip)
        
        return clips
    
    def render_text_image(
        self,
        text: str,
        width: int = 1080,
        height: int = 200,
        style: dict = None
    ) -> str:
        """Render text to a PNG image file."""
        Image = self.pillow["Image"]
        ImageDraw = self.pillow["ImageDraw"]
        
        style = style or {}
        
        # Create image
        img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        font = self._find_font(
            style.get("font", "Arial"),
            style.get("size", 48)
        )
        
        # Calculate text position
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = (width - text_width) // 2
        y = (height - text_height) // 2
        
        # Draw shadow
        if style.get("shadow", True):
            shadow_color = style.get("shadow_color", "black")
            offset = style.get("shadow_offset", (2, 2))
            draw.text((x + offset[0], y + offset[1]), text, font=font, fill=shadow_color)
        
        # Draw text
        color = style.get("color", "white")
        draw.text((x, y), text, font=font, fill=color)
        
        # Save
        output_path = f"/tmp/text_{hash(text)}.png"
        img.save(output_path)
        
        return output_path
