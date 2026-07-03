import uuid
from sqlalchemy import Column, String, Integer, Text, DateTime, func
from app.models.base import Base, TimestampMixin

class RepoFile(Base, TimestampMixin):
    __tablename__ = "repo_files"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    path = Column(String(500), unique=True, index=True, nullable=False)
    sha256_hash = Column(String(64), nullable=False)
    last_indexed_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

class RepoClass(Base, TimestampMixin):
    __tablename__ = "repo_classes"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    class_name = Column(String(255), index=True, nullable=False)
    file_path = Column(String(500), index=True, nullable=False)
    bases = Column(String(500), nullable=True) # Comma-separated list of bases
    docstring = Column(Text, nullable=True)
    start_line = Column(Integer, nullable=True)
    end_line = Column(Integer, nullable=True)

class RepoFunction(Base, TimestampMixin):
    __tablename__ = "repo_functions"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    function_name = Column(String(255), index=True, nullable=False)
    class_name = Column(String(255), index=True, nullable=True) # Null if top-level function
    file_path = Column(String(500), index=True, nullable=False)
    signature = Column(Text, nullable=True) # Method arguments and signature representation
    docstring = Column(Text, nullable=True)
    start_line = Column(Integer, nullable=True)
    end_line = Column(Integer, nullable=True)

class RepoRoute(Base, TimestampMixin):
    __tablename__ = "repo_routes"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    http_method = Column(String(10), nullable=False) # GET, POST, etc.
    route_path = Column(String(500), index=True, nullable=False)
    handler = Column(String(255), nullable=False) # Function/handler name
    file_path = Column(String(500), nullable=False)
