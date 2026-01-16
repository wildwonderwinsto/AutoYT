"""Audio mixing engine for video production."""

from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from pathlib import Path
import structlog

from app.config import settings

logger = structlog.get_logger()


@dataclass
class AudioTrack:
    """Represents an audio track for mixing."""
    path: str
    start_time: float = 0.0
    duration: Optional[float] = None  # None = full duration
    volume: float = 1.0  # 0.0 to 1.0
    fade_in: float = 0.0
    fade_out: float = 0.0
    loop: bool = False
    duck_during: List[Tuple[float, float]] = None  # List of (start, end) times to duck
    
    def __post_init__(self):
        if self.duck_during is None:
            self.duck_during = []


@dataclass 
class MixResult:
    """Result of audio mixing."""
    success: bool = False
    output_path: str = ""
    duration_seconds: float = 0.0
    error: str = ""


class AudioMixer:
    """
    Audio mixing engine for professional sound production.
    
    Features:
    - Multi-track mixing
    - Volume normalization
    - Audio ducking (lower music when voice plays)
    - Fade in/out transitions
    - Loop support for background music
    """
    
    # Ducking settings
    DUCK_VOLUME = 0.15  # Volume during ducking (15%)
    DUCK_FADE_TIME = 0.3  # Fade time for ducking transitions
    
    def __init__(self):
        self.output_dir = Path(settings.local_storage_path) / "audio" / "mixed"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self._pydub = None
    
    @property
    def pydub(self):
        """Lazy import pydub."""
        if self._pydub is None:
            try:
                from pydub import AudioSegment
                self._pydub = AudioSegment
            except ImportError:
                raise ImportError("pydub is required: pip install pydub")
        return self._pydub
    
    def load_audio(self, path: str) -> Any:
        """Load an audio file."""
        return self.pydub.from_file(path)
    
    def apply_ducking(
        self,
        background: Any,
        voice_segments: List[Tuple[float, float, Any]]
    ) -> Any:
        """
        Apply ducking to background audio during voice segments.
        
        Args:
            background: Background audio (pydub AudioSegment)
            voice_segments: List of (start_ms, end_ms, voice_audio) tuples
            
        Returns:
            Processed background audio with ducking applied
        """
        if not voice_segments:
            return background
        
        from pydub import effects
        
        # Sort segments by start time
        voice_segments = sorted(voice_segments, key=lambda x: x[0])
        
        # Create output
        result = self.pydub.silent(duration=len(background))
        current_pos = 0
        
        for start_ms, end_ms, _ in voice_segments:
            start_ms = int(start_ms)
            end_ms = int(end_ms)
            
            # Add fade margins
            duck_start = max(0, start_ms - int(self.DUCK_FADE_TIME * 1000))
            duck_end = min(len(background), end_ms + int(self.DUCK_FADE_TIME * 1000))
            
            # Normal volume before duck
            if duck_start > current_pos:
                normal_segment = background[current_pos:duck_start]
                result = result.overlay(normal_segment, position=current_pos)
            
            # Ducked section
            ducked_segment = background[duck_start:duck_end]
            ducked_segment = ducked_segment - (20 * (1 - self.DUCK_VOLUME))  # Reduce by dB
            
            # Apply fades
            fade_duration = int(self.DUCK_FADE_TIME * 1000)
            if len(ducked_segment) > fade_duration * 2:
                ducked_segment = ducked_segment.fade_in(fade_duration).fade_out(fade_duration)
            
            result = result.overlay(ducked_segment, position=duck_start)
            current_pos = duck_end
        
        # Add remaining normal audio
        if current_pos < len(background):
            remaining = background[current_pos:]
            result = result.overlay(remaining, position=current_pos)
        
        return result
    
    def mix_tracks(
        self,
        tracks: List[AudioTrack],
        output_filename: str,
        target_duration: float = None,
        normalize: bool = True
    ) -> MixResult:
        """
        Mix multiple audio tracks into a single output file.
        
        Args:
            tracks: List of AudioTrack objects
            output_filename: Output filename
            target_duration: Target duration in seconds (None = auto)
            normalize: Whether to normalize final output
            
        Returns:
            MixResult with output path
        """
        result = MixResult()
        
        if not tracks:
            result.error = "No tracks to mix"
            return result
        
        try:
            # Determine duration
            if target_duration:
                duration_ms = int(target_duration * 1000)
            else:
                # Use longest track
                durations = []
                for track in tracks:
                    audio = self.load_audio(track.path)
                    if track.duration:
                        durations.append(track.start_time * 1000 + track.duration * 1000)
                    else:
                        durations.append(track.start_time * 1000 + len(audio))
                duration_ms = int(max(durations))
            
            # Create base (silence)
            mixed = self.pydub.silent(duration=duration_ms)
            
            # Process each track
            voice_segments = []  # For ducking
            background_track = None
            
            for track in tracks:
                audio = self.load_audio(track.path)
                
                # Apply duration limit
                if track.duration:
                    audio = audio[:int(track.duration * 1000)]
                
                # Loop if needed
                if track.loop and len(audio) < duration_ms:
                    loops_needed = (duration_ms // len(audio)) + 1
                    audio = audio * loops_needed
                    audio = audio[:duration_ms]
                
                # Apply volume
                if track.volume != 1.0:
                    db_change = 20 * (track.volume - 1)  # Approximate dB
                    audio = audio + db_change
                
                # Apply fades
                if track.fade_in > 0:
                    audio = audio.fade_in(int(track.fade_in * 1000))
                if track.fade_out > 0:
                    audio = audio.fade_out(int(track.fade_out * 1000))
                
                # Track for ducking detection
                if track.duck_during:
                    # This is background music
                    background_track = (track, audio)
                elif "voice" in track.path.lower() or "tts" in track.path.lower():
                    # This is voice - record segments
                    voice_segments.append((
                        track.start_time * 1000,
                        track.start_time * 1000 + len(audio),
                        audio
                    ))
                
                # Overlay
                position = int(track.start_time * 1000)
                mixed = mixed.overlay(audio, position=position)
            
            # Apply ducking to background if we have voice segments
            if background_track and voice_segments:
                track, bg_audio = background_track
                ducked_bg = self.apply_ducking(bg_audio, voice_segments)
                
                # Remove original background and add ducked version
                # (This is a simplification - in practice we'd track this differently)
                position = int(track.start_time * 1000)
                # Re-mix with ducked background
                base = self.pydub.silent(duration=duration_ms)
                base = base.overlay(ducked_bg, position=position)
                
                # Add other tracks
                for t in tracks:
                    if t != track:
                        audio = self.load_audio(t.path)
                        if t.duration:
                            audio = audio[:int(t.duration * 1000)]
                        if t.volume != 1.0:
                            audio = audio + 20 * (t.volume - 1)
                        base = base.overlay(audio, position=int(t.start_time * 1000))
                
                mixed = base
            
            # Normalize
            if normalize:
                from pydub import effects
                mixed = effects.normalize(mixed)
            
            # Export
            output_path = str(self.output_dir / output_filename)
            mixed.export(output_path, format="wav")
            
            result.success = True
            result.output_path = output_path
            result.duration_seconds = len(mixed) / 1000.0
            
            logger.info(
                "Audio mixed",
                tracks=len(tracks),
                duration=result.duration_seconds,
                output=output_path
            )
            
        except Exception as e:
            logger.error(f"Audio mixing failed: {e}")
            result.error = str(e)
        
        return result
    
    def create_ranking_audio(
        self,
        bg_music_path: str,
        tts_results: Dict[str, Any],
        clip_durations: List[float],
        include_intro: bool = True,
        include_outro: bool = True
    ) -> MixResult:
        """
        Create complete audio track for a ranking video.
        
        Automatically positions voiceovers and applies ducking to background music.
        
        Args:
            bg_music_path: Path to background music file
            tts_results: Dict of TTS results (intro, rank_1, etc.)
            clip_durations: List of clip durations in order
            include_intro: Whether to include intro voiceover
            include_outro: Whether to include outro voiceover
            
        Returns:
            MixResult with final audio track
        """
        tracks = []
        current_time = 0.0
        voice_segments = []
        
        # Background music (looped, ducked)
        total_duration = sum(clip_durations) + 5.0  # Add padding
        
        tracks.append(AudioTrack(
            path=bg_music_path,
            start_time=0.0,
            volume=0.3,  # 30% base volume
            loop=True,
            fade_in=1.0,
            fade_out=2.0,
            duck_during=[]  # Will be filled
        ))
        
        # Intro (before clips)
        if include_intro and "intro" in tts_results:
            intro = tts_results["intro"]
            if intro.success:
                tracks.append(AudioTrack(
                    path=intro.audio_path,
                    start_time=0.5,
                    volume=1.0
                ))
                voice_segments.append((0.5, 0.5 + intro.duration_seconds))
                current_time = 0.5 + intro.duration_seconds + 0.5
        else:
            current_time = 0.5
        
        # Rank callouts (at start of each clip)
        for i, duration in enumerate(clip_durations):
            rank = len(clip_durations) - i  # Countdown
            rank_key = f"rank_{rank}"
            
            if rank_key in tts_results:
                tts = tts_results[rank_key]
                if tts.success:
                    tracks.append(AudioTrack(
                        path=tts.audio_path,
                        start_time=current_time,
                        volume=1.0
                    ))
                    voice_segments.append((
                        current_time,
                        current_time + tts.duration_seconds
                    ))
            
            current_time += duration
        
        # Outro
        if include_outro and "outro" in tts_results:
            outro = tts_results["outro"]
            if outro.success:
                tracks.append(AudioTrack(
                    path=outro.audio_path,
                    start_time=current_time,
                    volume=1.0
                ))
                voice_segments.append((
                    current_time,
                    current_time + outro.duration_seconds
                ))
                current_time += outro.duration_seconds + 1.0
        
        # Update background track with duck segments
        if tracks:
            tracks[0].duck_during = voice_segments
        
        # Mix all tracks
        return self.mix_tracks(
            tracks,
            f"ranking_audio_{hash(str(clip_durations))}.wav",
            target_duration=current_time
        )
    
    def extract_audio(self, video_path: str, output_path: str = None) -> str:
        """Extract audio from a video file."""
        try:
            from moviepy.editor import VideoFileClip
            
            video = VideoFileClip(video_path)
            
            if output_path is None:
                output_path = str(
                    self.output_dir / 
                    f"extracted_{Path(video_path).stem}.wav"
                )
            
            video.audio.write_audiofile(output_path)
            video.close()
            
            return output_path
            
        except Exception as e:
            logger.error(f"Audio extraction failed: {e}")
            return ""
    
    def normalize_audio(self, audio_path: str, target_db: float = -3.0) -> str:
        """Normalize audio to target dB level."""
        try:
            from pydub import effects
            
            audio = self.load_audio(audio_path)
            normalized = effects.normalize(audio, headroom=abs(target_db))
            
            output_path = audio_path.replace(".wav", "_normalized.wav")
            normalized.export(output_path, format="wav")
            
            return output_path
            
        except Exception as e:
            logger.error(f"Audio normalization failed: {e}")
            return audio_path
