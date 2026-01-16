"""Video effects engine for post-processing."""

from typing import Optional, Tuple, Any
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class EffectSettings:
    """Configuration for video effects."""
    # Color correction
    brightness: float = 1.0  # 0.5 to 1.5
    contrast: float = 1.0  # 0.5 to 1.5
    saturation: float = 1.0  # 0 to 2
    
    # Filters
    vignette: bool = False
    vignette_intensity: float = 0.3
    
    blur: bool = False
    blur_amount: float = 2.0
    
    sharpen: bool = False
    sharpen_amount: float = 1.5
    
    # Speed
    speed_factor: float = 1.0  # 0.5 to 2.0
    
    # Audio
    normalize_audio: bool = True
    audio_gain_db: float = 0.0


class EffectsEngine:
    """
    Video effects processing engine.
    
    Applies post-processing effects to video clips:
    - Color correction
    - Filters (vignette, blur, sharpen)
    - Speed adjustments
    - Audio normalization
    """
    
    def __init__(self):
        self._moviepy = None
        self._cv2 = None
    
    @property
    def moviepy(self):
        if self._moviepy is None:
            import moviepy.editor as mpy
            self._moviepy = mpy
        return self._moviepy
    
    @property
    def cv2(self):
        if self._cv2 is None:
            import cv2
            self._cv2 = cv2
        return self._cv2
    
    def apply_effects(self, clip, settings: EffectSettings = None):
        """Apply all configured effects to a clip."""
        settings = settings or EffectSettings()
        
        # Color correction
        if settings.brightness != 1.0:
            clip = self._adjust_brightness(clip, settings.brightness)
        
        if settings.contrast != 1.0:
            clip = self._adjust_contrast(clip, settings.contrast)
        
        if settings.saturation != 1.0:
            clip = self._adjust_saturation(clip, settings.saturation)
        
        # Filters
        if settings.vignette:
            clip = self._apply_vignette(clip, settings.vignette_intensity)
        
        if settings.sharpen:
            clip = self._apply_sharpen(clip, settings.sharpen_amount)
        
        # Speed
        if settings.speed_factor != 1.0:
            clip = clip.speedx(settings.speed_factor)
        
        # Audio
        if settings.normalize_audio and clip.audio:
            clip = self._normalize_audio(clip)
        
        if settings.audio_gain_db != 0.0 and clip.audio:
            clip = self._adjust_audio_gain(clip, settings.audio_gain_db)
        
        return clip
    
    def _adjust_brightness(self, clip, factor: float):
        """Adjust clip brightness."""
        mpy = self.moviepy
        
        def adjust_frame(frame):
            import numpy as np
            adjusted = np.clip(frame * factor, 0, 255).astype(np.uint8)
            return adjusted
        
        return clip.fl_image(adjust_frame)
    
    def _adjust_contrast(self, clip, factor: float):
        """Adjust clip contrast."""
        def adjust_frame(frame):
            import numpy as np
            mean = np.mean(frame)
            adjusted = np.clip((frame - mean) * factor + mean, 0, 255).astype(np.uint8)
            return adjusted
        
        return clip.fl_image(adjust_frame)
    
    def _adjust_saturation(self, clip, factor: float):
        """Adjust clip saturation."""
        cv2 = self.cv2
        
        def adjust_frame(frame):
            import numpy as np
            hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV).astype(np.float32)
            hsv[:, :, 1] = np.clip(hsv[:, :, 1] * factor, 0, 255)
            return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)
        
        return clip.fl_image(adjust_frame)
    
    def _apply_vignette(self, clip, intensity: float):
        """Apply vignette effect."""
        def apply_frame(frame):
            import numpy as np
            
            rows, cols = frame.shape[:2]
            
            # Create vignette mask
            X = np.arange(0, cols)
            Y = np.arange(0, rows)
            X, Y = np.meshgrid(X, Y)
            
            center_x, center_y = cols / 2, rows / 2
            
            # Gaussian mask
            mask = 1 - intensity * (
                ((X - center_x) ** 2 + (Y - center_y) ** 2) /
                (center_x ** 2 + center_y ** 2)
            )
            mask = np.clip(mask, 0.3, 1)
            
            # Apply mask
            result = frame.copy()
            for i in range(3):
                result[:, :, i] = (frame[:, :, i] * mask).astype(np.uint8)
            
            return result
        
        return clip.fl_image(apply_frame)
    
    def _apply_sharpen(self, clip, amount: float):
        """Apply sharpening filter."""
        cv2 = self.cv2
        
        def sharpen_frame(frame):
            import numpy as np
            
            # Sharpening kernel
            kernel = np.array([
                [-1, -1, -1],
                [-1, 9 * amount, -1],
                [-1, -1, -1]
            ]) / (1 + 8 * (amount - 1))
            
            return cv2.filter2D(frame, -1, kernel)
        
        return clip.fl_image(sharpen_frame)
    
    def _normalize_audio(self, clip):
        """Normalize clip audio."""
        try:
            return clip.audio_normalize()
        except Exception:
            return clip
    
    def _adjust_audio_gain(self, clip, db: float):
        """Adjust audio gain in decibels."""
        import math
        factor = math.pow(10, db / 20)
        return clip.volumex(factor)
    
    def create_zoom_effect(
        self,
        clip,
        start_scale: float = 1.0,
        end_scale: float = 1.2,
        center: Tuple[float, float] = (0.5, 0.5)
    ):
        """Create smooth zoom in/out effect."""
        mpy = self.moviepy
        
        def resize_func(t):
            progress = t / clip.duration
            scale = start_scale + (end_scale - start_scale) * progress
            return scale
        
        return clip.resize(resize_func)
    
    def create_pan_effect(
        self,
        clip,
        start_pos: Tuple[float, float],
        end_pos: Tuple[float, float]
    ):
        """Create panning effect across the frame."""
        def position_func(t):
            progress = t / clip.duration
            x = start_pos[0] + (end_pos[0] - start_pos[0]) * progress
            y = start_pos[1] + (end_pos[1] - start_pos[1]) * progress
            return (x, y)
        
        return clip.set_position(position_func)
    
    def apply_ken_burns(
        self,
        clip,
        target_size: Tuple[int, int],
        zoom_range: Tuple[float, float] = (1.0, 1.3),
        pan: bool = True
    ):
        """
        Apply Ken Burns effect (slow zoom + pan).
        
        Common for photos but can make video clips feel more dynamic.
        """
        import random
        mpy = self.moviepy
        
        w, h = target_size
        start_scale, end_scale = zoom_range
        
        # Random direction
        zoom_in = random.choice([True, False])
        if not zoom_in:
            start_scale, end_scale = end_scale, start_scale
        
        # Apply zoom
        clip = self.create_zoom_effect(clip, start_scale, end_scale)
        
        # Resize to target
        clip = clip.resize(target_size)
        
        return clip
