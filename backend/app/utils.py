import base64
import cv2
import numpy as np
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def encode_frame(frame: np.ndarray, quality: int = 80) -> str:
    """
    Encode a frame to base64 string
    
    Args:
        frame: OpenCV frame
        quality: JPEG quality (1-100)
        
    Returns:
        Base64 encoded string
    """
    try:
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return base64.b64encode(buffer).decode('utf-8')
    except Exception as e:
        logger.error(f"Error encoding frame: {e}")
        return ""

def decode_frame(encoded_frame: str) -> np.ndarray:
    """
    Decode a base64 encoded frame
    
    Args:
        encoded_frame: Base64 encoded string
        
    Returns:
        OpenCV frame
    """
    try:
        nparr = np.frombuffer(base64.b64decode(encoded_frame), np.uint8)
        return cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    except Exception as e:
        logger.error(f"Error decoding frame: {e}")
        return None

def get_timestamp_str() -> str:
    """Get current timestamp as string"""
    return datetime.now().isoformat()

def validate_client_id(client_id: str) -> bool:
    """Validate client ID format"""
    if not client_id or len(client_id) == 0:
        return False
    if len(client_id) > 255:
        return False
    return True

def format_duration(seconds: int) -> str:
    """Format seconds to HH:MM:SS"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def calculate_violation_score(violations: list) -> float:
    """Calculate severity score from violations (0-100)"""
    if not violations:
        return 0.0
    
    severity_weights = {
        "high": 3,
        "medium": 2,
        "low": 1
    }
    
    total_score = 0
    for violation in violations:
        severity = violation.get('severity', 'medium')
        weight = severity_weights.get(severity, 1)
        total_score += weight
    
    # Normalize to 0-100
    max_score = len(violations) * 3
    return min((total_score / max_score) * 100, 100.0)

def strip_header(b64):
    """Remove data URI header from base64 string"""
    if b64.startswith("data:"):
        return b64.split(",", 1)[1]
    return b64
