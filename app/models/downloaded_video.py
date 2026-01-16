"""Downloaded video database model"""

from sqlalchemy import Column, String, Text, BigInteger, Integer, Float, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class DownloadedVideo(Base):
    """Downloaded videos"""
    __tablename__ = "downloaded_videos"
    
    download_id = Column(
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
    local_path = Column(Text, nullable=False)
    s3_path = Column(Text, nullable=True)
    file_size_bytes = Column(BigInteger, nullable=True)
    resolution = Column(String(20), nullable=True)
    format = Column(String(20), nullable=True)
    fps = Column(Integer, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    downloaded_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now()
    )
    
    # Relationships
    content = relationship("PlatformContent", back_populates="download")
    
    # Indexes
    __table_args__ = (
        Index("idx_download_content", "content_id"),
    )
    
    def __repr__(self):
        return f"<DownloadedVideo {self.download_id}>"
