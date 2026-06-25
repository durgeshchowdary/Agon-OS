from sqlalchemy.orm import declarative_base, declared_attr
from sqlalchemy import Column, DateTime, func

Base = declarative_base()

class TimestampMixin:
    @declared_attr
    def created_at(cls):
        return Column(DateTime, default=func.now(), nullable=False)
        
    @declared_attr
    def updated_at(cls):
        return Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
