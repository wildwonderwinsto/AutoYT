"""Video editing pipeline for compilation and customization"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum
import os
from datetime import datetime
import structlog
from moviepy.editor import (
    VideoFileClip,
    TextClip,
    CompositeVideoClip,
    concatenate_videoclips,
    AudioFileClip,
    CompositeAudioClip,
    ColorClip
)
from moviepy.video.fx import all as vfx
import numpy as np

from app.config import settings

logger = structlog.get_logger()


class TransitionType(str, Enum):
    CUT = "cut"
    FADE = "fade"
    WIPE = "wipe"
    ZOOM = "zoom"


@dataclass
class CaptionStyle:
    """Caption styling configuration"""
    font: str = "Arial-Bold"
    font_size: int = 48
    color: str = "white"
    stroke_color: str = "black"
    stroke_width: int = 2
    position: Tuple[str, str] = ("center", "bottom")
    bg_color: Optional[str] = None
    bg_opacity: float = 0.5


@dataclass
class RankingOverlay:
    """Ranking number overlay configuration"""
    font: str = "Arial-Bold"
    font_size: int = 120
    color: str = "white"
    stroke_color: str = "black"
    stroke_width: int = 3
    position: Tuple[str, str] = ("left", "top")
    padding: int = 30
    animation: str = "fade"  # fade, zoom, slide


@dataclass
class AudioSettings:
    """Audio configuration for output"""
    background_music_path: Optional[str] = None
    background_volume: float = 0.2
    original_audio_volume: float = 0.8
    fade_in_duration: float = 0.5
    fade_out_duration: float = 0.5


@dataclass
class EditingConfig:
    """Complete editing configuration"""
    output_resolution: Tuple[int, int] = (1080, 1920)
    output_fps: int = 30
    output_format: str = "mp4"
    transition_type: TransitionType = TransitionType.FADE
    transition_duration: float = 0.3
    caption_style: CaptionStyle = field(default_factory=CaptionStyle)
    ranking_overlay: RankingOverlay = field(default_factory=RankingOverlay)
    audio_settings: AudioSettings = field(default_factory=AudioSettings)
    intro_clip_path: Optional[str] = None
    outro_clip_path: Optional[str] = None


@dataclass
class ClipInfo:
    """Information about a clip to be compiled"""
    path: str
    rank: Optional[int] = None
    start_time: float = 0.0
    end_time: Optional[float] = None
    caption: Optional[str] = None


@dataclass
class EditResult:
    """Result of video editing operation"""
    success: bool
    output_path: Optional[str] = None
    duration_seconds: Optional[float] = None
    file_size_bytes: Optional[int] = None
    resolution: Optional[str] = None
    error: Optional[str] = None


class VideoEditor:
    """Video editing pipeline for creating compilations"""
    
    def __init__(self, config: Optional[EditingConfig] = None):
        self.config = config or EditingConfig()
        self.output_path = Path(settings.local_storage_path) / "processed"
        self.temp_path = Path(settings.local_storage_path) / "temp"
        
        # Create directories
        self.output_path.mkdir(parents=True, exist_ok=True)
        self.temp_path.mkdir(parents=True, exist_ok=True)
    
    def compile_ranking_video(
        self,
        clips: List[ClipInfo],
        output_filename: str,
        title: Optional[str] = None
    ) -> EditResult:
        """Create a ranking compilation video"""
        logger.info("Starting ranking compilation", 
                   clips=len(clips), 
                   output=output_filename)
        
        try:
            processed_clips = []
            
            for clip_info in clips:
                clip = self._process_clip(clip_info)
                if clip:
                    processed_clips.append(clip)
            
            if not processed_clips:
                return EditResult(
                    success=False,
                    error="No clips could be processed"
                )
            
            # Apply transitions
            final_clips = self._apply_transitions(processed_clips)
            
            # Concatenate all clips
            final_video = concatenate_videoclips(final_clips, method="compose")
            
            # Add intro/outro if configured
            final_video = self._add_intro_outro(final_video)
            
            # Add background music
            final_video = self._add_background_music(final_video)
            
            # Set output path
            output_file = self.output_path / output_filename
            
            # Render final video
            final_video.write_videofile(
                str(output_file),
                fps=self.config.output_fps,
                codec="libx264",
                audio_codec="aac",
                preset="medium",
                threads=4
            )
            
            # Cleanup
            final_video.close()
            for clip in processed_clips:
                clip.close()
            
            # Get file info
            file_size = os.path.getsize(output_file)
            
            logger.info("Compilation complete", output=str(output_file))
            
            return EditResult(
                success=True,
                output_path=str(output_file),
                duration_seconds=final_video.duration,
                file_size_bytes=file_size,
                resolution=f"{self.config.output_resolution[0]}x{self.config.output_resolution[1]}"
            )
            
        except Exception as e:
            logger.error("Compilation failed", error=str(e))
            return EditResult(
                success=False,
                error=str(e)
            )
    
    def _process_clip(self, clip_info: ClipInfo) -> Optional[VideoFileClip]:
        """Process a single clip with effects and overlays"""
        try:
            # Load video clip
            clip = VideoFileClip(clip_info.path)
            
            # Trim if specified
            if clip_info.start_time > 0 or clip_info.end_time:
                end = clip_info.end_time or clip.duration
                clip = clip.subclip(clip_info.start_time, end)
            
            # Resize to match output resolution
            target_w, target_h = self.config.output_resolution
            clip = clip.resize(height=target_h)
            
            # Center crop if wider than target
            if clip.w > target_w:
                x_center = clip.w // 2
                x1 = x_center - (target_w // 2)
                clip = clip.crop(x1=x1, x2=x1 + target_w)
            
            # Pad if narrower than target
            elif clip.w < target_w:
                clip = clip.on_color(
                    size=(target_w, target_h),
                    color=(0, 0, 0),
                    pos="center"
                )
            
            # Add ranking overlay if specified
            if clip_info.rank is not None:
                clip = self._add_ranking_overlay(clip, clip_info.rank)
            
            # Add caption if specified
            if clip_info.caption:
                clip = self._add_caption(clip, clip_info.caption)
            
            return clip
            
        except Exception as e:
            logger.error("Failed to process clip", 
                        path=clip_info.path, 
                        error=str(e))
            return None
    
    def _add_ranking_overlay(
        self,
        clip: VideoFileClip,
        rank: int
    ) -> CompositeVideoClip:
        """Add ranking number overlay to clip"""
        overlay_config = self.config.ranking_overlay
        
        # Create ranking text
        rank_text = TextClip(
            f"#{rank}",
            fontsize=overlay_config.font_size,
            font=overlay_config.font,
            color=overlay_config.color,
            stroke_color=overlay_config.stroke_color,
            stroke_width=overlay_config.stroke_width
        )
        
        # Position the text
        rank_text = rank_text.set_position((
            overlay_config.padding,
            overlay_config.padding
        )).set_duration(clip.duration)
        
        # Apply animation
        if overlay_config.animation == "fade":
            rank_text = rank_text.crossfadein(0.3)
        elif overlay_config.animation == "zoom":
            rank_text = rank_text.fx(vfx.resize, lambda t: 1 + 0.5 * max(0, 0.5 - t))
        
        return CompositeVideoClip([clip, rank_text])
    
    def _add_caption(
        self,
        clip: VideoFileClip,
        text: str
    ) -> CompositeVideoClip:
        """Add caption text to clip"""
        style = self.config.caption_style
        
        # Create caption text
        caption = TextClip(
            text,
            fontsize=style.font_size,
            font=style.font,
            color=style.color,
            stroke_color=style.stroke_color,
            stroke_width=style.stroke_width,
            method="caption",
            size=(clip.w - 40, None)
        )
        
        # Add background if configured
        if style.bg_color:
            bg = ColorClip(
                size=(clip.w, caption.h + 20),
                color=self._hex_to_rgb(style.bg_color)
            ).set_opacity(style.bg_opacity)
            
            caption = CompositeVideoClip([bg, caption.set_position("center")])
        
        # Position caption
        caption = caption.set_position(("center", clip.h - caption.h - 50))
        caption = caption.set_duration(clip.duration)
        
        return CompositeVideoClip([clip, caption])
    
    def _apply_transitions(
        self,
        clips: List[VideoFileClip]
    ) -> List[VideoFileClip]:
        """Apply transitions between clips"""
        if len(clips) <= 1:
            return clips
        
        transition_type = self.config.transition_type
        duration = self.config.transition_duration
        
        if transition_type == TransitionType.CUT:
            return clips
        
        processed = []
        for i, clip in enumerate(clips):
            if transition_type == TransitionType.FADE:
                if i > 0:
                    clip = clip.crossfadein(duration)
                if i < len(clips) - 1:
                    clip = clip.crossfadeout(duration)
            
            processed.append(clip)
        
        return processed
    
    def _add_intro_outro(self, video: VideoFileClip) -> VideoFileClip:
        """Add intro and outro clips if configured"""
        clips_to_join = []
        
        if self.config.intro_clip_path and os.path.exists(self.config.intro_clip_path):
            intro = VideoFileClip(self.config.intro_clip_path)
            intro = intro.resize(height=self.config.output_resolution[1])
            clips_to_join.append(intro)
        
        clips_to_join.append(video)
        
        if self.config.outro_clip_path and os.path.exists(self.config.outro_clip_path):
            outro = VideoFileClip(self.config.outro_clip_path)
            outro = outro.resize(height=self.config.output_resolution[1])
            clips_to_join.append(outro)
        
        if len(clips_to_join) > 1:
            return concatenate_videoclips(clips_to_join, method="compose")
        
        return video
    
    def _add_background_music(self, video: VideoFileClip) -> VideoFileClip:
        """Add background music to video"""
        audio_settings = self.config.audio_settings
        
        if not audio_settings.background_music_path:
            return video
        
        if not os.path.exists(audio_settings.background_music_path):
            logger.warning("Background music file not found", 
                          path=audio_settings.background_music_path)
            return video
        
        try:
            # Load background music
            bg_music = AudioFileClip(audio_settings.background_music_path)
            
            # Loop if shorter than video
            if bg_music.duration < video.duration:
                loops_needed = int(video.duration / bg_music.duration) + 1
                bg_music = concatenate_audioclips([bg_music] * loops_needed)
            
            # Trim to video length
            bg_music = bg_music.subclip(0, video.duration)
            
            # Adjust volume
            bg_music = bg_music.volumex(audio_settings.background_volume)
            
            # Apply fade in/out
            if audio_settings.fade_in_duration > 0:
                bg_music = bg_music.audio_fadein(audio_settings.fade_in_duration)
            if audio_settings.fade_out_duration > 0:
                bg_music = bg_music.audio_fadeout(audio_settings.fade_out_duration)
            
            # Adjust original audio volume
            if video.audio:
                original_audio = video.audio.volumex(audio_settings.original_audio_volume)
                
                # Mix audio tracks
                final_audio = CompositeAudioClip([original_audio, bg_music])
                video = video.set_audio(final_audio)
            else:
                video = video.set_audio(bg_music)
            
            return video
            
        except Exception as e:
            logger.error("Failed to add background music", error=str(e))
            return video
    
    def _hex_to_rgb(self, hex_color: str) -> Tuple[int, int, int]:
        """Convert hex color to RGB tuple"""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    def extract_clip_segment(
        self,
        input_path: str,
        start_time: float,
        end_time: float,
        output_filename: str
    ) -> EditResult:
        """Extract a segment from a video"""
        try:
            clip = VideoFileClip(input_path)
            segment = clip.subclip(start_time, end_time)
            
            output_file = self.temp_path / output_filename
            segment.write_videofile(
                str(output_file),
                fps=self.config.output_fps,
                codec="libx264"
            )
            
            segment.close()
            clip.close()
            
            return EditResult(
                success=True,
                output_path=str(output_file),
                duration_seconds=end_time - start_time
            )
            
        except Exception as e:
            logger.error("Failed to extract segment", error=str(e))
            return EditResult(
                success=False,
                error=str(e)
            )
