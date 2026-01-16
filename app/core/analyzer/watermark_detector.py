"""Watermark detection using template matching and OCR."""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
import structlog

logger = structlog.get_logger()


@dataclass
class WatermarkResult:
    """Watermark detection results."""
    has_watermark: bool = False
    confidence: float = 0.0
    watermark_type: str = "none"  # tiktok, instagram, username, custom
    location: str = ""  # corner position if detected
    detected_text: List[str] = None
    
    def __post_init__(self):
        if self.detected_text is None:
            self.detected_text = []


class WatermarkDetector:
    """
    Detects watermarks in video frames.
    
    Uses multiple detection methods:
    1. Template matching for known platform logos (TikTok, Instagram)
    2. Corner region analysis for custom watermarks
    3. Optional OCR for text-based watermarks (username overlays)
    """
    
    # Known watermark positions (normalized coordinates)
    CORNER_REGIONS = {
        "top_left": (0, 0, 0.2, 0.15),
        "top_right": (0.8, 0, 1.0, 0.15),
        "bottom_left": (0, 0.85, 0.2, 1.0),
        "bottom_right": (0.8, 0.85, 1.0, 1.0),
        "top_center": (0.35, 0, 0.65, 0.1),
        "bottom_center": (0.35, 0.9, 0.65, 1.0)
    }
    
    def __init__(self, template_dir: str = None):
        self.template_dir = Path(template_dir) if template_dir else None
        self._cv2 = None
        self._templates: Dict[str, Any] = {}
    
    @property
    def cv2(self):
        if self._cv2 is None:
            try:
                import cv2
                self._cv2 = cv2
            except ImportError:
                raise ImportError("opencv-python is required")
        return self._cv2
    
    def detect_in_frame(
        self,
        frame,
        check_corners: bool = True,
        check_templates: bool = True,
        check_text: bool = False
    ) -> WatermarkResult:
        """
        Detect watermarks in a single frame.
        
        Args:
            frame: OpenCV image (numpy array)
            check_corners: Check corner regions for logos
            check_templates: Use template matching for known logos
            check_text: Use OCR for text detection (slower)
            
        Returns:
            WatermarkResult with detection details
        """
        result = WatermarkResult()
        
        height, width = frame.shape[:2]
        
        # Check corners for likely watermark regions
        if check_corners:
            corner_result = self._check_corners(frame, width, height)
            if corner_result:
                result.has_watermark = True
                result.location = corner_result["location"]
                result.confidence = corner_result["confidence"]
                result.watermark_type = "corner_logo"
        
        # Template matching for known logos
        if check_templates and self.template_dir and not result.has_watermark:
            template_result = self._template_match(frame)
            if template_result:
                result.has_watermark = True
                result.watermark_type = template_result["type"]
                result.confidence = template_result["confidence"]
        
        # OCR for text watermarks (optional, slower)
        if check_text and not result.has_watermark:
            text_result = self._detect_text_watermark(frame)
            if text_result:
                result.has_watermark = True
                result.watermark_type = "username"
                result.detected_text = text_result["text"]
                result.confidence = text_result["confidence"]
        
        return result
    
    def detect_in_video(
        self,
        video_path: str,
        sample_count: int = 3
    ) -> WatermarkResult:
        """
        Detect watermarks by sampling multiple frames from a video.
        
        Uses voting across frames - if majority have watermarks, video is marked.
        """
        cap = self.cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            logger.error(f"Could not open video: {video_path}")
            return WatermarkResult()
        
        try:
            import numpy as np
            
            total_frames = int(cap.get(self.cv2.CAP_PROP_FRAME_COUNT))
            
            if total_frames <= 0:
                return WatermarkResult()
            
            # Sample frames
            frame_indices = np.linspace(
                int(total_frames * 0.1),  # Skip first 10%
                int(total_frames * 0.9),  # Skip last 10%
                sample_count,
                dtype=int
            )
            
            detections = []
            
            for idx in frame_indices:
                cap.set(self.cv2.CAP_PROP_POS_FRAMES, idx)
                ret, frame = cap.read()
                
                if ret and frame is not None:
                    result = self.detect_in_frame(frame)
                    detections.append(result)
            
            # Vote on results
            watermark_count = sum(1 for d in detections if d.has_watermark)
            
            if watermark_count >= len(detections) / 2:
                # Majority have watermarks
                # Return the result with highest confidence
                best = max(
                    [d for d in detections if d.has_watermark],
                    key=lambda x: x.confidence,
                    default=WatermarkResult()
                )
                return best
            
            return WatermarkResult()
            
        finally:
            cap.release()
    
    def _check_corners(
        self,
        frame,
        width: int,
        height: int
    ) -> Optional[Dict[str, Any]]:
        """
        Check corner regions for potential watermarks.
        
        Uses edge detection and contour analysis to find logo-like shapes.
        """
        import numpy as np
        
        for location, (x1, y1, x2, y2) in self.CORNER_REGIONS.items():
            # Convert normalized coords to pixels
            px1, py1 = int(x1 * width), int(y1 * height)
            px2, py2 = int(x2 * width), int(y2 * height)
            
            # Extract region
            region = frame[py1:py2, px1:px2]
            
            if region.size == 0:
                continue
            
            # Convert to grayscale
            gray = self.cv2.cvtColor(region, self.cv2.COLOR_BGR2GRAY)
            
            # Edge detection
            edges = self.cv2.Canny(gray, 50, 150)
            
            # Find contours
            contours, _ = self.cv2.findContours(
                edges,
                self.cv2.RETR_EXTERNAL,
                self.cv2.CHAIN_APPROX_SIMPLE
            )
            
            # Look for logo-like shapes
            region_area = (px2 - px1) * (py2 - py1)
            
            for contour in contours:
                area = self.cv2.contourArea(contour)
                
                # Logo typically takes up 10-50% of corner region
                if 0.1 * region_area < area < 0.5 * region_area:
                    # Check if it's roughly square or circular (logo-like)
                    x, y, w, h = self.cv2.boundingRect(contour)
                    aspect_ratio = w / h if h > 0 else 0
                    
                    if 0.5 < aspect_ratio < 2.0:
                        confidence = min(area / region_area * 2, 0.9)
                        return {
                            "location": location,
                            "confidence": confidence
                        }
        
        return None
    
    def _template_match(self, frame) -> Optional[Dict[str, Any]]:
        """
        Match against known watermark templates.
        
        Requires template images in the template_dir.
        """
        if not self.template_dir or not self.template_dir.exists():
            return None
        
        # Load templates if not already loaded
        if not self._templates:
            self._load_templates()
        
        if not self._templates:
            return None
        
        gray_frame = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
        
        best_match = None
        best_score = 0.7  # Minimum threshold
        
        for name, template in self._templates.items():
            # Scale template to match frame size
            for scale in [0.5, 0.75, 1.0, 1.25]:
                scaled_template = self.cv2.resize(
                    template,
                    None,
                    fx=scale,
                    fy=scale
                )
                
                if (scaled_template.shape[0] > gray_frame.shape[0] or
                    scaled_template.shape[1] > gray_frame.shape[1]):
                    continue
                
                result = self.cv2.matchTemplate(
                    gray_frame,
                    scaled_template,
                    self.cv2.TM_CCOEFF_NORMED
                )
                
                _, max_val, _, _ = self.cv2.minMaxLoc(result)
                
                if max_val > best_score:
                    best_score = max_val
                    best_match = name
        
        if best_match:
            return {
                "type": best_match,
                "confidence": best_score
            }
        
        return None
    
    def _load_templates(self):
        """Load watermark template images."""
        if not self.template_dir:
            return
        
        template_files = list(self.template_dir.glob("*.png"))
        
        for template_path in template_files:
            try:
                template = self.cv2.imread(str(template_path), 0)  # Grayscale
                if template is not None:
                    name = template_path.stem  # e.g., "tiktok", "instagram"
                    self._templates[name] = template
                    logger.debug(f"Loaded template: {name}")
            except Exception as e:
                logger.warning(f"Failed to load template {template_path}: {e}")
    
    def _detect_text_watermark(self, frame) -> Optional[Dict[str, Any]]:
        """
        OCR-based text watermark detection.
        
        Checks corner regions for username-like text overlays.
        """
        try:
            import pytesseract
        except ImportError:
            logger.debug("pytesseract not available for OCR")
            return None
        
        height, width = frame.shape[:2]
        detected_text = []
        
        # Only check corners
        corner_checks = ["bottom_left", "bottom_right", "top_right"]
        
        for location in corner_checks:
            x1, y1, x2, y2 = self.CORNER_REGIONS[location]
            px1, py1 = int(x1 * width), int(y1 * height)
            px2, py2 = int(x2 * width), int(y2 * height)
            
            region = frame[py1:py2, px1:px2]
            
            if region.size == 0:
                continue
            
            try:
                # Run OCR
                text = pytesseract.image_to_string(
                    region,
                    config='--psm 7'  # Single text line
                ).strip()
                
                # Filter for username patterns (@ symbol or short text)
                if text and (text.startswith("@") or len(text) < 20):
                    detected_text.append(text)
                    
            except Exception as e:
                logger.debug(f"OCR failed for {location}: {e}")
        
        if detected_text:
            return {
                "text": detected_text,
                "confidence": 0.7
            }
        
        return None
