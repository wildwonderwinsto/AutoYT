"""Tests for video editor module"""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


class TestVideoEditor:
    """Test VideoEditor class"""
    
    def test_initialization_default_config(self):
        """Test editor initializes with default config"""
        with patch('app.core.editor.settings') as mock_settings:
            mock_settings.local_storage_path = "./storage"
            
            from app.core.editor import VideoEditor, EditingConfig
            
            editor = VideoEditor()
            
            assert editor.config is not None
            assert isinstance(editor.config, EditingConfig)
    
    def test_initialization_custom_config(self):
        """Test editor initializes with custom config"""
        with patch('app.core.editor.settings') as mock_settings:
            mock_settings.local_storage_path = "./storage"
            
            from app.core.editor import VideoEditor, EditingConfig
            
            config = EditingConfig(
                output_resolution=(720, 1280),
                output_fps=60
            )
            
            editor = VideoEditor(config)
            
            assert editor.config.output_resolution == (720, 1280)
            assert editor.config.output_fps == 60


class TestEditingConfig:
    """Test EditingConfig dataclass"""
    
    def test_default_values(self):
        """Test default configuration values"""
        from app.core.editor import EditingConfig
        
        config = EditingConfig()
        
        assert config.output_resolution == (1080, 1920)
        assert config.output_fps == 30
        assert config.output_format == "mp4"
    
    def test_custom_values(self):
        """Test custom configuration values"""
        from app.core.editor import EditingConfig, TransitionType
        
        config = EditingConfig(
            output_resolution=(1440, 2560),
            transition_type=TransitionType.ZOOM,
            transition_duration=0.5
        )
        
        assert config.output_resolution == (1440, 2560)
        assert config.transition_type == TransitionType.ZOOM
        assert config.transition_duration == 0.5


class TestCaptionStyle:
    """Test CaptionStyle dataclass"""
    
    def test_default_style(self):
        """Test default caption style"""
        from app.core.editor import CaptionStyle
        
        style = CaptionStyle()
        
        assert style.font == "Arial-Bold"
        assert style.font_size == 48
        assert style.color == "white"
    
    def test_custom_style(self):
        """Test custom caption style"""
        from app.core.editor import CaptionStyle
        
        style = CaptionStyle(
            font="Helvetica",
            font_size=72,
            color="yellow",
            bg_color="black",
            bg_opacity=0.7
        )
        
        assert style.font == "Helvetica"
        assert style.font_size == 72
        assert style.bg_opacity == 0.7


class TestClipInfo:
    """Test ClipInfo dataclass"""
    
    def test_minimal_clip_info(self):
        """Test creating ClipInfo with minimal data"""
        from app.core.editor import ClipInfo
        
        clip = ClipInfo(path="/path/to/video.mp4")
        
        assert clip.path == "/path/to/video.mp4"
        assert clip.rank is None
        assert clip.start_time == 0.0
        assert clip.end_time is None
    
    def test_full_clip_info(self):
        """Test creating ClipInfo with all data"""
        from app.core.editor import ClipInfo
        
        clip = ClipInfo(
            path="/path/to/video.mp4",
            rank=1,
            start_time=5.0,
            end_time=15.0,
            caption="Top video of the day!"
        )
        
        assert clip.rank == 1
        assert clip.start_time == 5.0
        assert clip.end_time == 15.0
        assert clip.caption == "Top video of the day!"


class TestEditResult:
    """Test EditResult dataclass"""
    
    def test_success_result(self):
        """Test successful edit result"""
        from app.core.editor import EditResult
        
        result = EditResult(
            success=True,
            output_path="/path/to/output.mp4",
            duration_seconds=60.5,
            file_size_bytes=50000000,
            resolution="1080x1920"
        )
        
        assert result.success is True
        assert result.output_path == "/path/to/output.mp4"
        assert result.error is None
    
    def test_failure_result(self):
        """Test failed edit result"""
        from app.core.editor import EditResult
        
        result = EditResult(
            success=False,
            error="FFmpeg encoding failed"
        )
        
        assert result.success is False
        assert result.error == "FFmpeg encoding failed"
        assert result.output_path is None


class TestTransitionType:
    """Test TransitionType enum"""
    
    def test_transition_values(self):
        """Test all transition type values exist"""
        from app.core.editor import TransitionType
        
        assert TransitionType.CUT.value == "cut"
        assert TransitionType.FADE.value == "fade"
        assert TransitionType.WIPE.value == "wipe"
        assert TransitionType.ZOOM.value == "zoom"


class TestHexToRgb:
    """Test hex to RGB conversion"""
    
    def test_hex_conversion(self):
        """Test hex color to RGB conversion"""
        with patch('app.core.editor.settings') as mock_settings:
            mock_settings.local_storage_path = "./storage"
            
            from app.core.editor import VideoEditor
            
            editor = VideoEditor()
            
            # Test white
            assert editor._hex_to_rgb("#FFFFFF") == (255, 255, 255)
            
            # Test black
            assert editor._hex_to_rgb("#000000") == (0, 0, 0)
            
            # Test red
            assert editor._hex_to_rgb("#FF0000") == (255, 0, 0)
            
            # Without hash
            assert editor._hex_to_rgb("00FF00") == (0, 255, 0)
