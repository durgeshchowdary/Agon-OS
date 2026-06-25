import json
import logging
import re
from pydantic import BaseModel
from typing import List
from app.agents.base import BaseAgent
from app.llm.factory import LLMFactory

logger = logging.getLogger(__name__)

class ReviewDecision(BaseModel):
    title: str
    severity: str
    recommendation: str

from typing import Optional

class ReviewerOutput(BaseModel):
    # Sprint 7 Fields
    approved: bool = True
    summary: Optional[str] = None

    # Phase 3 Fields
    overall_assessment: Optional[str] = None
    strengths: List[str] = []
    issues: List[str] = []
    recommendations: List[str] = []
    approval_status: Optional[str] = None
    confidence: float = 0.0

    # Backward compatibility fields (optional)
    executive_summary: Optional[str] = None
    weaknesses: List[str] = []
    scalability_issues: List[str] = []
    security_concerns: List[str] = []
    cost_risks: List[str] = []
    architectural_gaps: List[str] = []
    alternative_approaches: List[str] = []
    review_decisions: List[ReviewDecision] = []

class CriticAgent(BaseAgent):
    def __init__(self, llm_provider=None):
        super().__init__(name="Reviewer", role="Design Reviewer")
        self.llm_provider = llm_provider or LLMFactory.get_provider()
        
    async def run(self, initial_prompt: str, prd_content: str, architecture_content: str) -> ReviewerOutput:
        system_prompt = (
            "You are the Design Reviewer and QA Specialist at AGON OS. Your task is to evaluate and challenge "
            "the proposed Product Requirements Document (PRD) and System Architecture.\n\n"
            "CRITICAL RULES:\n"
            "- You must NOT generate requirements or architecture from scratch.\n"
            "- You must NOT rewrite the PM outputs or Architect outputs.\n"
            "- You must NOT write implementation code or frontend components.\n"
            "- Your focus is strictly on challenging, critiquing, and finding bottlenecks, scalability issues, security risks, "
            "cost risks, operational risks, and suggesting alternative approaches.\n\n"
            "You MUST output your response as a valid JSON object matching this schema:\n"
            "{\n"
            "  \"executive_summary\": \"Overall summary of the architecture audit and status\",\n"
            "  \"strengths\": [\"Strength 1\", \"Strength 2\", ...],\n"
            "  \"weaknesses\": [\"Weakness 1\", \"Weakness 2\", ...],\n"
            "  \"scalability_issues\": [\"Scalability bottleneck 1\", ...],\n"
            "  \"security_concerns\": [\"Security risk 1\", ...],\n"
            "  \"cost_risks\": [\"Cost risk 1\", ...],\n"
            "  \"architectural_gaps\": [\"Architectural gap 1\", ...],\n"
            "  \"alternative_approaches\": [\"Alternative approach 1\", ...],\n"
            "  \"review_decisions\": [\n"
            "    {\n"
            "      \"title\": \"Missing audit logging\",\n"
            "      \"severity\": \"High\",\n"
            "      \"recommendation\": \"Implement database triggers or middleware to log user edits to a ledger.\"\n"
            "    }\n"
            "  ],\n"
            "  \"confidence\": 0.90\n"
            "}\n"
            "Do not include any explanation, markdown formatting (like ```json), or additional text outside the JSON structure."
        )
        
        user_prompt = (
            f"Software Idea: {initial_prompt}\n\n"
            f"Requirements (PRD):\n{prd_content}\n\n"
            f"System Architecture:\n{architecture_content}\n"
        )

        retries = 2
        last_error = None
        for attempt in range(retries):
            try:
                import inspect
                sig = inspect.signature(self.llm_provider.generate)
                if "response_schema" in sig.parameters:
                    response_str = await self.llm_provider.generate(system_prompt, user_prompt, response_schema=ReviewerOutput)
                else:
                    response_str = await self.llm_provider.generate(system_prompt, user_prompt)
                cleaned_str = self._clean_json_string(response_str)
                reviewer_output = ReviewerOutput.model_validate_json(cleaned_str)
                
                # Cross-populate fields for safety and backward compatibility
                if reviewer_output.summary and not reviewer_output.overall_assessment:
                    reviewer_output.overall_assessment = reviewer_output.summary
                if reviewer_output.overall_assessment and not reviewer_output.summary:
                    reviewer_output.summary = reviewer_output.overall_assessment
                if reviewer_output.executive_summary and not reviewer_output.summary:
                    reviewer_output.summary = reviewer_output.executive_summary
                if reviewer_output.summary and not reviewer_output.executive_summary:
                    reviewer_output.executive_summary = reviewer_output.summary
                
                if reviewer_output.approval_status == "APPROVED":
                    reviewer_output.approved = True
                elif reviewer_output.approval_status in ("REJECTED", "CHANGES_REQUESTED"):
                    reviewer_output.approved = False
                elif reviewer_output.approved is True and not reviewer_output.approval_status:
                    reviewer_output.approval_status = "APPROVED"
                elif reviewer_output.approved is False and not reviewer_output.approval_status:
                    reviewer_output.approval_status = "REJECTED"
                    
                return reviewer_output
            except Exception as e:
                last_error = e
                logger.warning(f"Reviewer agent generation/validation failed on attempt {attempt + 1}: {e}")
                if attempt == 0:
                    user_prompt += f"\n\nCorrection from previous attempt: Your last response failed validation with error: {str(e)}. Please output valid JSON matching the schema strictly without extra markdown formatting."

        raise ValueError(f"Failed to generate valid Reviewer output after {retries} attempts. Last error: {str(last_error)}")

    def _clean_json_string(self, text: str) -> str:
        text = text.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()
        return text

    def format_review(self, output: ReviewerOutput) -> str:
        summary = output.overall_assessment or output.executive_summary or "Review Summary"
        strengths_md = "\n".join([f"- {s}" for s in output.strengths])
        
        # Determine whether it's new structure or old structure
        if output.issues or output.recommendations or output.approval_status:
            issues_md = "\n".join([f"- {i}" for i in output.issues])
            recs_md = "\n".join([f"- {r}" for r in output.recommendations])
            approval_status = output.approval_status or "PENDING"
            
            # Map issues/recommendations to review_decisions for database compatibility
            if not output.review_decisions and output.issues:
                output.review_decisions = []
                for i, issue in enumerate(output.issues):
                    rec = output.recommendations[i] if i < len(output.recommendations) else "No recommendation"
                    output.review_decisions.append(
                        ReviewDecision(title=issue, severity="Medium", recommendation=rec)
                    )
            
            decisions_md = ""
            for i, dec in enumerate(output.review_decisions, 1):
                decisions_md += f"### {i}. {dec.title}\n- **Severity**: {dec.severity}\n- **Recommendation**: {dec.recommendation}\n\n"
                
            return f"""# Architecture Review & Security Audit

## 1. Overall Assessment
{summary}

## 2. Strengths
{strengths_md}

## 3. Issues Identified
{issues_md}

## 4. Recommendations
{recs_md}

## 5. Approval Status
- **Status**: {approval_status}

## 6. Review Decisions
{decisions_md}
---
*Confidence Score: {output.confidence:.2f}*
"""
        else:
            weaknesses_md = "\n".join([f"- {w}" for w in output.weaknesses])
            scalability_md = "\n".join([f"- {item}" for item in output.scalability_issues])
            security_md = "\n".join([f"- {item}" for item in output.security_concerns])
            cost_md = "\n".join([f"- {item}" for item in output.cost_risks])
            gaps_md = "\n".join([f"- {item}" for item in output.architectural_gaps])
            alternatives_md = "\n".join([f"- {item}" for item in output.alternative_approaches])
            
            decisions_md = ""
            for i, dec in enumerate(output.review_decisions, 1):
                decisions_md += f"### {i}. {dec.title}\n- **Severity**: {dec.severity}\n- **Recommendation**: {dec.recommendation}\n\n"

            return f"""# Architecture Review & Security Audit

## 1. Executive Summary
{summary}

## 2. Strengths
{strengths_md}

## 3. Weaknesses & Bottlenecks
{weaknesses_md}

## 4. Scalability Issues
{scalability_md}

## 5. Security Concerns
{security_md}

## 6. Cost Risks
{cost_md}

## 7. Architectural Gaps
{gaps_md}

## 8. Alternative Approaches & Recommendations
{alternatives_md}

## 9. Review Decisions
{decisions_md}
---
*Confidence Score: {output.confidence:.2f}*
"""
