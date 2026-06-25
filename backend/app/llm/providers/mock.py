import json
import logging
from typing import Optional
from pydantic import BaseModel
from app.llm.base import LLMProvider

logger = logging.getLogger(__name__)

class MockLLMProvider(LLMProvider):
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Optional[type[BaseModel]] = None
    ) -> str:
        logger.info("MockLLMProvider generating response (schema: %s)", response_schema.__name__ if response_schema else None)
        
        # Detect agent by system prompt or schema type to return appropriate structured mock responses
        if response_schema:
            schema_name = response_schema.__name__
            if schema_name == "PMOutput":
                return (
                    '{"summary": "GST Filing Application", "requirements": ["Req 1", "Req 2"], '
                    '"user_stories": ["Story 1"], "risks": ["Risk 1"], '
                    '"decisions": ["Use SQLite for local", "Use REST APIs"], "confidence": 0.95}'
                )
            elif schema_name == "ArchitectOutput":
                return (
                    '{"executive_summary": "Architecture summary", "architecture_overview": "Overview pattern", '
                    '"recommended_stack": ["FastAPI", "SQLite"], "database_design": ["DDL table"], '
                    '"api_design": ["POST /api/v1/tax"], "system_components": ["Tax calculator"], '
                    '"tradeoffs": ["FastAPI vs Django"], "risks": ["Tax compliance update lag"], '
                    '"scalability_considerations": ["Horizontal scale"], '
                    '"decisions": [{"title": "DB Selection", "description": "Relational choice", '
                    '"options": ["SQLite", "Mongo"], "selected_option": "SQLite", "rationale": "ACID"}], '
                    '"confidence": 0.95}'
                )
            elif schema_name == "ReviewerOutput":
                # Returns both the new fields and old compatibility fields populated
                return (
                    '{"overall_assessment": "Review summary", "strengths": ["Str"], "issues": ["Issue 1"], '
                    '"recommendations": ["Recommendation 1"], "approval_status": "APPROVED", '
                    '"executive_summary": "Review summary", "weaknesses": ["Weak"], '
                    '"scalability_issues": ["Scale"], "security_concerns": ["Security"], "cost_risks": ["Cost"], '
                    '"architectural_gaps": ["Gap"], "alternative_approaches": ["Alt"], '
                    '"review_decisions": [{"title": "Authentication concerns", "severity": "Medium", '
                    '"recommendation": "Encrypt payload"}], "confidence": 0.92}'
                )
            
            # Generic fallback generator if none of the above matches
            mock_dict = {}
            for field_name, field_info in response_schema.model_fields.items():
                annotation = field_info.annotation
                if annotation == str or annotation == Optional[str]:
                    mock_dict[field_name] = f"Mock {field_name}"
                elif annotation == float or annotation == Optional[float]:
                    mock_dict[field_name] = 0.9
                elif annotation == int or annotation == Optional[int]:
                    mock_dict[field_name] = 1
                elif annotation == bool or annotation == Optional[bool]:
                    mock_dict[field_name] = True
                elif getattr(annotation, "__origin__", None) == list:
                    mock_dict[field_name] = []
                else:
                    mock_dict[field_name] = None
            return json.dumps(mock_dict)

        # Fallback if no schema is passed (like CTOAgent or generic)
        if "Lead Product Manager" in system_prompt:
            return (
                '{"summary": "Mock summary", "requirements": ["Req 1"], "user_stories": ["Story 1"], '
                '"risks": ["Risk 1"], "decisions": ["Decision 1"], "confidence": 0.9}'
            )
        elif "Principal System Architect" in system_prompt:
            return (
                '{"executive_summary": "Summary", "architecture_overview": "Overview", '
                '"recommended_stack": ["React", "FastAPI"], "database_design": ["Table users"], '
                '"api_design": ["GET /users"], "system_components": ["Auth"], "tradeoffs": ["SQL vs NoSQL"], '
                '"risks": ["Auth latency"], "scalability_considerations": ["Caching"], '
                '"decisions": [{"title": "DB Choice", "description": "Relational choice", '
                '"options": ["Postgre", "Mongo"], "selected_option": "Postgre", "rationale": "ACID"}], '
                '"confidence": 0.95}'
            )
        elif "Design Reviewer and QA" in system_prompt:
            return (
                '{"executive_summary": "Review summary", "strengths": ["Str"], "weaknesses": ["Weak"], '
                '"scalability_issues": ["Scale"], "security_concerns": ["Security"], "cost_risks": ["Cost"], '
                '"architectural_gaps": ["Gap"], "alternative_approaches": ["Alt"], '
                '"review_decisions": [{"title": "Authentication concerns", "severity": "Medium", '
                '"recommendation": "Encrypt payload"}], "confidence": 0.92}'
            )
        
        return "Mock response from MockLLMProvider"
