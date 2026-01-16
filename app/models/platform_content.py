"""Platform content database model"""

from sqlalchemy import Column, String, Text, BigInteger, Integer, Float, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class PlatformContent(Base):
    """Platform content: Raw discovered videos from platforms"""
    __tablename__ = "platform_content"
    
    content_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )
    platform = Column(String(50), nullable=False, index=True)
    platform_video_id = Column(String(255), nullable=False)
    url = Column(Text, nullable=False)
    title = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    author = Column(String(255), nullable=True)
    views = Column(BigInteger, nullable=True)
    likes = Column(BigInteger, nullable=True)
    comments = Column(BigInteger, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    upload_date = Column(TIMESTAMP(timezone=True), nullable=True)
    trending_score = Column(Float, nullable=True, index=True)
    metadata = Column(JSONB, nullable=True)
    discovered_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now()
    )
    
    # Relationships
    job = relationship("Job", back_populates="platform_content")
    analysis = relationship(
        "VideoAnalysis",
        back_populates="content",
        uselist=False,
        cascade="all, delete-orphan"
    )
    download = relationship(
        "DownloadedVideo",
        back_populates="content",
        uselist=False,
        cascade="all, delete-orphan"
    )
    
    # Indexes and constraints
    __table_args__ = (
        Index("idx_job_platform", "job_id", "platform"),
        Index("idx_trending_score", "trending_score"),
        Index("idx_platform_video", "platform", "platform_video_id", unique=True),
    )
    
    def __repr__(self):
        return f"<PlatformContent {self.platform}:{self.platform_video_id}>"
