from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional

class ReviewFinding(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    category: str       # "Architecture", "Security", "Duplication", "Tests", "Maintainability", "Dependencies"
    severity: str       # "Critical", "High", "Medium", "Low"
    file_path: str
    line_number: Optional[int] = None
    finding_title: str
    description: str
    recommendation: str

class CodeReviewOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    status: str         # "PASS", "WARNING", "FAIL"
    summary: str
    score: float
    findings: List[ReviewFinding]
    confidence: float
