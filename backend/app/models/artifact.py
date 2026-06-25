import uuid
from sqlalchemy import Column, String, Text, ForeignKey, Integer
from sqlalchemy.orm import relationship
from app.models.base import Base, TimestampMixin

class ProjectArtifact(Base, TimestampMixin):
    __tablename__ = "project_artifacts"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True)
    artifact_type = Column(String(50), nullable=False)  # REQUIREMENTS, ARCHITECTURE, DATABASE, API, etc.
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    review_cycle_number = Column(Integer, default=1, nullable=False)
    status = Column(String(50), default="DRAFT", nullable=False)  # DRAFT, APPROVED, REJECTED
    
    # Relationships
    project = relationship("Project", back_populates="artifacts")
    run = relationship("AgentRun", back_populates="artifacts")
