"""Local quality checking utilities (no AI required)."""

from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass
from pathlib import Path
import structlog

logger = structlog.get_logger()


@dataclass
class QualityReport:
    """Quality check results."""
    passed: bool = True
    is_vertical: bool = True
    has_black_bars: bool = False
    resolution_ok: bool = True
    duration_ok: bool = True
    width: int = 0
    height: int = 0
    duration_seconds: float = 0.0
    fps: float = 0.0
    file_size_mb: float = 0.0
    issues: List[str] = None
    
    def __post_init__(self):
        if self.issues is None:
            self.issues = []


class QualityChecker:
    """
    Fast local quality checks without AI.
    
    Performs basic validation:
    - Resolution and aspect ratio
    - Duration limits
    - File size limits
    - FPS validation
    - Black bar detection
    """
    
    # Quality thresholds
    MIN_WIDTH = 720
    MIN_HEIGHT = 1280
    MIN_FPS = 24
    MAX_DURATION = 61  # Shorts are max 60 seconds
    MIN_DURATION = 5
    MAX_FILE_SIZE_MB = 500
    VERTICAL_ASPECT_RATIO = 16 / 9  # 9:16 inverted = 1.78
    
    def __init__(self):
        self._cv2 = None
    
    @property
    def cv2(self):
        if self._cv2 is None:
            try:
                import cv2
                self._cv2 = cv2
            except ImportError:
                raise ImportError("opencv-python is required for quality checking")
        return self._cv2
    
    def check_video(self, video_path: str) -> QualityReport:
        """
        Run all quality checks on a video file.
        
        Args:
            video_path: Path to the video file
            
        Returns:
            QualityReport with all check results
        """
        report = QualityReport()
        path = Path(video_path)
        
        if not path.exists():
            report.passed = False
            report.issues.append(f"File not found: {video_path}")
            return report
        
        # Get file size
        report.file_size_mb = path.stat().st_size / (1024 * 1024)
        
        if report.file_size_mb > self.MAX_FILE_SIZE_MB:
            report.passed = False
            report.issues.append(f"File too large: {report.file_size_mb:.1f}MB (max {self.MAX_FILE_SIZE_MB}MB)")
        
        # Open video
        cap = self.cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            report.passed = False
            report.issues.append("Could not open video file")
            return report
        
        try:
            # Get video properties
            report.width = int(cap.get(self.cv2.CAP_PROP_FRAME_WIDTH))
            report.height = int(cap.get(self.cv2.CAP_PROP_FRAME_HEIGHT))
            report.fps = cap.get(self.cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(self.cv2.CAP_PROP_FRAME_COUNT))
            report.duration_seconds = frame_count / report.fps if report.fps > 0 else 0
            
            # Check orientation
            report.is_vertical = report.height > report.width
            
            if not report.is_vertical:
                report.passed = False
                report.issues.append(f"Video is horizontal ({report.width}x{report.height}), needs vertical")
            
            # Check resolution
            if report.is_vertical:
                if report.height < self.MIN_HEIGHT or report.width < self.MIN_WIDTH:
                    report.resolution_ok = False
                    report.issues.append(
                        f"Resolution too low: {report.width}x{report.height} "
                        f"(min {self.MIN_WIDTH}x{self.MIN_HEIGHT})"
                    )
            
            # Check FPS
            if report.fps < self.MIN_FPS:
                report.issues.append(f"Low FPS: {report.fps:.1f} (min {self.MIN_FPS})")
            
            # Check duration
            if report.duration_seconds > self.MAX_DURATION:
                report.duration_ok = False
                report.issues.append(
                    f"Video too long: {report.duration_seconds:.1f}s (max {self.MAX_DURATION}s)"
                )
            elif report.duration_seconds < self.MIN_DURATION:
                report.duration_ok = False
                report.issues.append(
                    f"Video too short: {report.duration_seconds:.1f}s (min {self.MIN_DURATION}s)"
                )
            
            # Check for black bars
            report.has_black_bars = self._detect_black_bars(cap, report.width, report.height)
            
            if report.has_black_bars:
                report.issues.append("Video appears to have black bars/letterboxing")
            
            # Final pass determination
            report.passed = (
                report.is_vertical and
                report.resolution_ok and
                report.duration_ok and
                not report.has_black_bars and
                len(report.issues) == 0
            )
            
        finally:
            cap.release()
        
        logger.debug(
            "Quality check complete",
            video=video_path,
            passed=report.passed,
            issues=report.issues
        )
        
        return report
    
    def _detect_black_bars(
        self,
        cap,
        width: int,
        height: int,
        threshold: float = 0.1
    ) -> bool:
        """
        Detect if video has black bars on sides or top/bottom.
        
        Samples a frame and checks edge regions for predominantly black pixels.
        """
        try:
            import numpy as np
            
            # Get middle frame
            total_frames = int(cap.get(self.cv2.CAP_PROP_FRAME_COUNT))
            cap.set(self.cv2.CAP_PROP_POS_FRAMES, total_frames // 2)
            ret, frame = cap.read()
            
            if not ret or frame is None:
                return False
            
            # Convert to grayscale
            gray = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
            
            # Check left and right edges (for pillarboxing)
            edge_width = int(width * 0.05)  # 5% of width
            left_edge = gray[:, :edge_width]
            right_edge = gray[:, -edge_width:]
            
            # Check top and bottom edges (for letterboxing)
            edge_height = int(height * 0.05)  # 5% of height
            top_edge = gray[:edge_height, :]
            bottom_edge = gray[-edge_height:, :]
            
            # Calculate mean brightness (black = 0)
            edges = [left_edge, right_edge, top_edge, bottom_edge]
            edge_means = [np.mean(edge) for edge in edges]
            
            # If any edge is mostly black (mean < 15), likely has bars
            black_threshold = 15
            has_bars = any(mean < black_threshold for mean in edge_means)
            
            return has_bars
            
        except Exception as e:
            logger.warning(f"Black bar detection failed: {e}")
            return False
    
    def get_video_info(self, video_path: str) -> Dict[str, Any]:
        """Get detailed video information."""
        report = self.check_video(video_path)
        
        return {
            "width": report.width,
            "height": report.height,
            "duration_seconds": report.duration_seconds,
            "fps": report.fps,
            "file_size_mb": report.file_size_mb,
            "is_vertical": report.is_vertical,
            "has_black_bars": report.has_black_bars,
            "aspect_ratio": f"{report.width}:{report.height}",
            "resolution": f"{report.width}x{report.height}",
            "quality_passed": report.passed,
            "issues": report.issues
        }


class BatchQualityChecker:
    """Check quality of multiple videos efficiently."""
    
    def __init__(self):
        self.checker = QualityChecker()
    
    def check_batch(
        self,
        video_paths: List[str]
    ) -> Dict[str, QualityReport]:
        """
        Check multiple videos.
        
        Returns dict mapping path to report.
        """
        results = {}
        
        for path in video_paths:
            try:
                results[path] = self.checker.check_video(path)
            except Exception as e:
                logger.error(f"Quality check failed for {path}: {e}")
                report = QualityReport(passed=False)
                report.issues.append(str(e))
                results[path] = report
        
        return results
    
    def filter_passed(
        self,
        video_paths: List[str]
    ) -> Tuple[List[str], List[str]]:
        """
        Filter videos by quality check.
        
        Returns:
            Tuple of (passed_paths, failed_paths)
        """
        passed = []
        failed = []
        
        results = self.check_batch(video_paths)
        
        for path, report in results.items():
            if report.passed:
                passed.append(path)
            else:
                failed.append(path)
        
        return passed, failed
