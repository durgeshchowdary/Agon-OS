import uuid
from sqlalchemy import Column, String, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.models.base import Base, TimestampMixin

class Project(Base, TimestampMixin):
    __tablename__ = "projects"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    creator_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    domain = Column(String(50), default="software_engineering", nullable=False)
    
    # Relationships
    creator = relationship("User", back_populates="projects")
    runs = relationship("AgentRun", back_populates="project", cascade="all, delete-orphan")
    artifacts = relationship("ProjectArtifact", back_populates="project", cascade="all, delete-orphan")
    decisions = relationship("Decision", back_populates="project", cascade="all, delete-orphan")

class Decision(Base, TimestampMixin):
    __tablename__ = "decisions"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    options = Column(JSON, nullable=True)  # Store options list: [{"name": "A", "pros": [], "cons": []}]
    selected_option = Column(String(255), nullable=True)
    rationale = Column(Text, nullable=True)
    
    # Relationships
    project = relationship("Project", back_populates="decisions")
    run = relationship("AgentRun", back_populates="decisions")
