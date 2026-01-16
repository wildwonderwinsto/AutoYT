"""Customization preset database model"""

from sqlalchemy import Column, String, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class CustomizationPreset(Base):
    """User customization presets (for manual options)"""
    __tablename__ = "customization_presets"
    
    preset_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    user_id = Column(String(255), nullable=False, index=True)
    preset_name = Column(String(255), nullable=False)
    caption_style = Column(JSONB, nullable=True)  # Font, size, color, position, animation
    audio_settings = Column(JSONB, nullable=True)  # Background music preferences, volume levels
    transition_style = Column(String(50), nullable=True)  # 'cut', 'fade', 'wipe', 'zoom'
    ranking_overlay = Column(JSONB, nullable=True)  # Number style, position, animation
    created_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now()
    )
    
    # Indexes
    __table_args__ = (
        Index("idx_preset_user", "user_id"),
    )
    
    def __repr__(self):
        return f"<CustomizationPreset {self.preset_name}>"
