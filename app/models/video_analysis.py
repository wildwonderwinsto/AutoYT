"""Video analysis database model"""

from sqlalchemy import Column, String, Text, Float, Boolean, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class VideoAnalysis(Base):
    """AI Analysis results"""
    __tablename__ = "video_analysis"
    
    analysis_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    content_id = Column(
        UUID(as_uuid=True),
        ForeignKey("platform_content.content_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    ai_model = Column(String(100), nullable=False)
    quality_score = Column(Float, nullable=True)
    virality_score = Column(Float, nullable=True)
    relevance_score = Column(Float, nullable=True)
    content_summary = Column(Text, nullable=True)
    detected_topics = Column(ARRAY(Text), nullable=True)
    visual_analysis = Column(JSONB, nullable=True)
    sentiment = Column(String(50), nullable=True)
    recommended = Column(Boolean, default=False)
    analyzed_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now()
    )
    
    # Relationships
    content = relationship("PlatformContent", back_populates="analysis")
    
    # Indexes
    __table_args__ = (
        Index("idx_recommended", "content_id", "recommended"),
        Index("idx_scores", "quality_score", "virality_score", "relevance_score"),
    )
    
    def __repr__(self):
        return f"<VideoAnalysis {self.analysis_id} (recommended={self.recommended})>"
