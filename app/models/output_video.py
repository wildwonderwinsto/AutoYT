"""Output video database model"""

from sqlalchemy import Column, String, Text, BigInteger, Float, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class OutputVideo(Base):
    """Compiled output videos"""
    __tablename__ = "output_videos"
    
    output_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    tags = Column(ARRAY(Text), nullable=True)
    ranking_items = Column(JSONB, nullable=True)  # Array of {rank, content_id, start_time, end_time}
    local_path = Column(Text, nullable=False)
    s3_path = Column(Text, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    resolution = Column(String(20), nullable=True)
    file_size_bytes = Column(BigInteger, nullable=True)
    manual_edits = Column(JSONB, nullable=True)  # User's manual customizations
    render_settings = Column(JSONB, nullable=True)  # Captions, audio, effects settings
    created_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now()
    )
    
    # Relationships
    job = relationship("Job", back_populates="output_videos")
    
    # Indexes
    __table_args__ = (
        Index("idx_output_job", "job_id"),
    )
    
    def __repr__(self):
        return f"<OutputVideo {self.output_id} ({self.title})>"
