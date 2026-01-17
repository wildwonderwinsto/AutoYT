"""Job database model"""

from sqlalchemy import Column, String, Text, Enum, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum

from app.core.database import Base


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    DISCOVERING = "discovering"
    ANALYZING = "analyzing"
    DOWNLOADING = "downloading"
    EDITING = "editing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobType(str, enum.Enum):
    RANKING = "ranking"
    COMPILATION = "compilation"
    HIGHLIGHTS = "highlights"


class Job(Base):
    """Jobs table: Tracks automation jobs"""
    __tablename__ = "jobs"
    
    job_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    user_id = Column(String(255), nullable=False, index=True)
    job_type = Column(String(50), nullable=False)
    status = Column(
        String(50),
        default=JobStatus.PENDING,
        index=True
    )
    config = Column(JSONB, nullable=False)
    created_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now()
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    logs = Column(JSONB, nullable=True, default=list)  # Array of log entries
    
    # Relationships
    platform_content = relationship(
        "PlatformContent",
        back_populates="job",
        cascade="all, delete-orphan"
    )
    output_videos = relationship(
        "OutputVideo",
        back_populates="job",
        cascade="all, delete-orphan"
    )
    
    # Indexes
    __table_args__ = (
        Index("idx_user_status", "user_id", "status"),
        Index("idx_created", "created_at"),
    )
    
    def __repr__(self):
        return f"<Job {self.job_id} ({self.status})>"
