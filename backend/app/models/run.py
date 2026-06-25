import uuid
from sqlalchemy import Column, String, Text, ForeignKey, Integer, DateTime
from sqlalchemy.orm import relationship
from app.models.base import Base, TimestampMixin

class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(50), default="PENDING", nullable=False)  # PENDING, RUNNING, COMPLETED, FAILED
    initial_prompt = Column(Text, nullable=False)
    current_stage = Column(String(50), nullable=True)  # PM, ARCHITECT, REVIEWER
    review_cycle_number = Column(Integer, default=1, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    project = relationship("Project", back_populates="runs")
    steps = relationship("AgentStep", back_populates="run", cascade="all, delete-orphan")
    artifacts = relationship("ProjectArtifact", back_populates="run", cascade="all, delete-orphan")
    decisions = relationship("Decision", back_populates="run")
    approvals = relationship("Approval", back_populates="run", cascade="all, delete-orphan")

class AgentStep(Base, TimestampMixin):
    __tablename__ = "agent_steps"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    agent_name = Column(String(50), nullable=False)  # PM, ARCHITECT, CRITIC, CTO
    step_type = Column(String(50), nullable=False)   # THOUGHT, DEBATE, ARTIFACT_PROPOSAL, CRITIQUE, APPROVAL
    content = Column(Text, nullable=False)
    sequence_number = Column(Integer, nullable=False)
    
    # Relationships
    run = relationship("AgentRun", back_populates="steps")

class Approval(Base, TimestampMixin):
    __tablename__ = "approvals"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    stage = Column(String(50), nullable=False)  # PM, ARCHITECT, REVIEWER
    status = Column(String(50), default="PENDING", nullable=False)  # PENDING, APPROVED, REJECTED
    approved_by = Column(String(255), nullable=True)  # Stored as username/email/system string
    approved_at = Column(DateTime, nullable=True)
    comments = Column(Text, nullable=True)
    rationale = Column(Text, nullable=True)
    review_cycle_number = Column(Integer, default=1, nullable=False)
    
    # Relationships
    run = relationship("AgentRun", back_populates="approvals")

