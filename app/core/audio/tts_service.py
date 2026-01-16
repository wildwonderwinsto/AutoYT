"""Text-to-Speech service for voiceover generation."""

from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum
import hashlib
import structlog

from app.config import settings

logger = structlog.get_logger()


class VoiceStyle(Enum):
    """Available voice styles for narration."""
    ENERGETIC = "energetic"
    CALM = "calm"
    DRAMATIC = "dramatic"
    CASUAL = "casual"


@dataclass
class VoiceConfig:
    """Configuration for TTS voice."""
    language_code: str = "en-US"
    voice_name: str = "en-US-Neural2-C"  # Energetic male voice
    gender: str = "MALE"
    speaking_rate: float = 1.1  # Slightly faster for TikTok pacing
    pitch: float = 0.0
    volume_gain_db: float = 0.0


# Preset voice configurations
VOICE_PRESETS: Dict[VoiceStyle, VoiceConfig] = {
    VoiceStyle.ENERGETIC: VoiceConfig(
        voice_name="en-US-Neural2-C",
        gender="MALE",
        speaking_rate=1.15,
        pitch=1.0
    ),
    VoiceStyle.CALM: VoiceConfig(
        voice_name="en-US-Neural2-D",
        gender="MALE",
        speaking_rate=0.95,
        pitch=-1.0
    ),
    VoiceStyle.DRAMATIC: VoiceConfig(
        voice_name="en-US-Neural2-A",
        gender="MALE",
        speaking_rate=0.9,
        pitch=-2.0
    ),
    VoiceStyle.CASUAL: VoiceConfig(
        voice_name="en-US-Neural2-I",
        gender="FEMALE",
        speaking_rate=1.05,
        pitch=0.0
    ),
}


@dataclass
class TTSResult:
    """Result of TTS generation."""
    success: bool = False
    audio_path: str = ""
    duration_seconds: float = 0.0
    text: str = ""
    error: str = ""


class TTSService:
    """
    Text-to-Speech service for generating professional voiceovers.
    
    Supports multiple providers:
    - Google Cloud TTS (primary, highest quality)
    - OpenAI TTS (fallback)
    - Local pyttsx3 (offline fallback)
    """
    
    def __init__(
        self,
        voice_style: VoiceStyle = VoiceStyle.ENERGETIC,
        cache_enabled: bool = True
    ):
        self.voice_config = VOICE_PRESETS.get(voice_style, VOICE_PRESETS[VoiceStyle.ENERGETIC])
        self.cache_enabled = cache_enabled
        
        # Storage paths
        self.audio_dir = Path(settings.local_storage_path) / "audio"
        self.temp_dir = self.audio_dir / "temp"
        self.cache_dir = self.audio_dir / "cache"
        
        for dir_path in [self.audio_dir, self.temp_dir, self.cache_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize providers lazily
        self._google_client = None
        self._openai_client = None
    
    def _get_cache_key(self, text: str) -> str:
        """Generate a cache key for the text."""
        content = f"{text}_{self.voice_config.voice_name}_{self.voice_config.speaking_rate}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def _check_cache(self, text: str) -> Optional[str]:
        """Check if audio is already cached."""
        if not self.cache_enabled:
            return None
        
        cache_key = self._get_cache_key(text)
        cache_path = self.cache_dir / f"{cache_key}.wav"
        
        if cache_path.exists():
            logger.debug(f"TTS cache hit: {cache_key}")
            return str(cache_path)
        
        return None
    
    def _save_to_cache(self, text: str, audio_path: str) -> str:
        """Save audio to cache and return cache path."""
        if not self.cache_enabled:
            return audio_path
        
        import shutil
        
        cache_key = self._get_cache_key(text)
        cache_path = self.cache_dir / f"{cache_key}.wav"
        
        shutil.copy(audio_path, cache_path)
        return str(cache_path)
    
    def generate_speech(
        self,
        text: str,
        filename: str = None,
        provider: str = "auto"
    ) -> TTSResult:
        """
        Generate speech audio from text.
        
        Args:
            text: Text to synthesize
            filename: Optional output filename (without extension)
            provider: "google", "openai", "local", or "auto"
            
        Returns:
            TTSResult with audio path and metadata
        """
        result = TTSResult(text=text)
        
        # Check cache first
        cached = self._check_cache(text)
        if cached:
            result.success = True
            result.audio_path = cached
            result.duration_seconds = self._get_audio_duration(cached)
            return result
        
        # Generate filename if not provided
        if not filename:
            filename = f"tts_{hashlib.md5(text.encode()).hexdigest()[:8]}"
        
        output_path = str(self.temp_dir / f"{filename}.wav")
        
        # Try providers in order
        if provider == "auto":
            providers = ["google", "openai", "local"]
        else:
            providers = [provider]
        
        for prov in providers:
            try:
                if prov == "google":
                    success = self._generate_google(text, output_path)
                elif prov == "openai":
                    success = self._generate_openai(text, output_path)
                elif prov == "local":
                    success = self._generate_local(text, output_path)
                else:
                    continue
                
                if success:
                    # Cache the result
                    cached_path = self._save_to_cache(text, output_path)
                    
                    result.success = True
                    result.audio_path = cached_path
                    result.duration_seconds = self._get_audio_duration(cached_path)
                    
                    logger.info(
                        "TTS generated",
                        text_length=len(text),
                        provider=prov,
                        duration=result.duration_seconds
                    )
                    return result
                    
            except Exception as e:
                logger.warning(f"TTS provider {prov} failed: {e}")
                continue
        
        result.error = "All TTS providers failed"
        return result
    
    def _generate_google(self, text: str, output_path: str) -> bool:
        """Generate speech using Google Cloud TTS."""
        try:
            from google.cloud import texttospeech
        except ImportError:
            logger.debug("Google Cloud TTS not available")
            return False
        
        if self._google_client is None:
            try:
                self._google_client = texttospeech.TextToSpeechClient()
            except Exception as e:
                logger.warning(f"Google TTS init failed: {e}")
                return False
        
        try:
            synthesis_input = texttospeech.SynthesisInput(text=text)
            
            voice = texttospeech.VoiceSelectionParams(
                language_code=self.voice_config.language_code,
                name=self.voice_config.voice_name,
                ssml_gender=getattr(
                    texttospeech.SsmlVoiceGender,
                    self.voice_config.gender
                )
            )
            
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                speaking_rate=self.voice_config.speaking_rate,
                pitch=self.voice_config.pitch,
                volume_gain_db=self.voice_config.volume_gain_db
            )
            
            response = self._google_client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
            
            with open(output_path, "wb") as out:
                out.write(response.audio_content)
            
            return True
            
        except Exception as e:
            logger.error(f"Google TTS failed: {e}")
            return False
    
    def _generate_openai(self, text: str, output_path: str) -> bool:
        """Generate speech using OpenAI TTS."""
        try:
            from openai import OpenAI
        except ImportError:
            logger.debug("OpenAI not available")
            return False
        
        if self._openai_client is None:
            try:
                self._openai_client = OpenAI(api_key=settings.openai_api_key)
            except Exception as e:
                logger.warning(f"OpenAI init failed: {e}")
                return False
        
        try:
            # Map voice config to OpenAI voices
            voice_map = {
                "MALE": "onyx",
                "FEMALE": "nova"
            }
            voice = voice_map.get(self.voice_config.gender, "alloy")
            
            response = self._openai_client.audio.speech.create(
                model="tts-1-hd",
                voice=voice,
                input=text,
                response_format="wav",
                speed=self.voice_config.speaking_rate
            )
            
            response.stream_to_file(output_path)
            return True
            
        except Exception as e:
            logger.error(f"OpenAI TTS failed: {e}")
            return False
    
    def _generate_local(self, text: str, output_path: str) -> bool:
        """Generate speech using local pyttsx3 (offline fallback)."""
        try:
            import pyttsx3
        except ImportError:
            logger.debug("pyttsx3 not available")
            return False
        
        try:
            engine = pyttsx3.init()
            engine.setProperty('rate', int(150 * self.voice_config.speaking_rate))
            
            # Save to file
            engine.save_to_file(text, output_path)
            engine.runAndWait()
            
            return Path(output_path).exists()
            
        except Exception as e:
            logger.error(f"Local TTS failed: {e}")
            return False
    
    def _get_audio_duration(self, audio_path: str) -> float:
        """Get duration of audio file in seconds."""
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(audio_path)
            return len(audio) / 1000.0
        except Exception:
            return 0.0
    
    # High-level methods for ranking videos
    
    def generate_intro(self, niche: str, count: int) -> TTSResult:
        """Generate the opening voiceover for a ranking video."""
        text = f"Here are the top {count} {niche} videos of the week!"
        return self.generate_speech(text, f"intro_{niche}")
    
    def generate_rank_callout(self, rank: int, title: str = None) -> TTSResult:
        """Generate voiceover for a ranking number."""
        if title:
            # Clean title
            clean_title = title[:50] if len(title) > 50 else title
            text = f"Number {rank}. {clean_title}"
        else:
            text = f"Number {rank}"
        
        return self.generate_speech(text, f"rank_{rank}")
    
    def generate_outro(self, cta: str = None) -> TTSResult:
        """Generate closing voiceover."""
        if cta:
            text = cta
        else:
            text = "Like and subscribe for more! Which one was your favorite? Comment below!"
        
        return self.generate_speech(text, "outro")
    
    def generate_ranking_audio_set(
        self,
        niche: str,
        clips: List[Dict[str, Any]]
    ) -> Dict[str, TTSResult]:
        """
        Generate all audio needed for a ranking video.
        
        Returns dict with keys: intro, rank_1, rank_2, ..., outro
        """
        audio_set = {}
        
        # Intro
        audio_set["intro"] = self.generate_intro(niche, len(clips))
        
        # Each rank
        for i, clip in enumerate(clips):
            rank = len(clips) - i  # Countdown order
            title = clip.get("caption_suggestion") or clip.get("title", "")
            audio_set[f"rank_{rank}"] = self.generate_rank_callout(rank, title)
        
        # Outro
        audio_set["outro"] = self.generate_outro()
        
        return audio_set
    
    def cleanup_temp_files(self):
        """Remove temporary audio files."""
        for file in self.temp_dir.iterdir():
            if file.is_file():
                try:
                    file.unlink()
                except Exception:
                    pass
