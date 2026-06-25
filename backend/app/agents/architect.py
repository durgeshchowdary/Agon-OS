import json
import logging
import re
from pydantic import BaseModel
from typing import List, Optional
from app.agents.base import BaseAgent
from app.llm.factory import LLMFactory

logger = logging.getLogger(__name__)

class ArchitectDecision(BaseModel):
    title: str
    description: str
    options: List[str]
    selected_option: str
    rationale: str

class ArchitectOutput(BaseModel):
    executive_summary: str
    architecture_overview: str
    recommended_stack: List[str]
    database_design: List[str]
    api_design: List[str]
    system_components: List[str]
    tradeoffs: List[str]
    risks: List[str]
    scalability_considerations: List[str]
    decisions: List[ArchitectDecision]
    confidence: float

class ArchitectAgent(BaseAgent):
    def __init__(self, llm_provider=None):
        super().__init__(name="Architect", role="System Architect")
        self.llm_provider = llm_provider or LLMFactory.get_provider()
        
    async def run(
        self,
        initial_prompt: str,
        prd_content: str,
        debate_history: list = None,
        revision_mode: bool = False,
        previous_architecture: Optional[str] = None,
        reviewer_issues: Optional[List[str]] = None,
        reviewer_recommendations: Optional[List[str]] = None
    ) -> ArchitectOutput:
        system_prompt = (
            "You are the Principal System Architect at AGON OS. Analyze the user prompt and the Product "
            "Requirements Document (PRD) to design a complete system architecture.\n\n"
            "CRITICAL RULES:\n"
            "- You must NOT write implementation code or frontend components.\n"
            "- You must NOT generate user stories or repeat PM requirements.\n"
            "- You must focus purely on technical design, database schemas, and API design.\n\n"
            "You MUST output your response as a valid JSON object matching this schema:\n"
            "{\n"
            "  \"executive_summary\": \"High level technical design executive summary\",\n"
            "  \"architecture_overview\": \"Overview of the system architecture pattern\",\n"
            "  \"recommended_stack\": [\"Stack item 1\", \"Stack item 2\", ...],\n"
            "  \"database_design\": [\"Database Schema description/DDL 1\", \"Database Schema description/DDL 2\", ...],\n"
            "  \"api_design\": [\"API endpoint contract 1\", \"API endpoint contract 2\", ...],\n"
            "  \"system_components\": [\"Component 1 description\", \"Component 2 description\", ...],\n"
            "  \"tradeoffs\": [\"Tradeoff 1\", \"Tradeoff 2\", ...],\n"
            "  \"risks\": [\"Risk 1\", \"Risk 2\", ...],\n"
            "  \"scalability_considerations\": [\"Consideration 1\", \"Consideration 2\", ...],\n"
            "  \"decisions\": [\n"
            "    {\n"
            "      \"title\": \"Database Choice\",\n"
            "      \"description\": \"Choosing relational vs non-relational database\",\n"
            "      \"options\": [\"PostgreSQL\", \"MongoDB\"],\n"
            "      \"selected_option\": \"PostgreSQL\",\n"
            "      \"rationale\": \"Strict compliance and schema requirements.\"\n"
            "    }\n"
            "  ],\n"
            "  \"confidence\": 0.95\n"
            "}\n"
            "Do not include any explanation, markdown formatting (like ```json), or additional text outside the JSON structure."
        )
        
        user_prompt = (
            f"Software Idea: {initial_prompt}\n\n"
            f"PRD Context:\n{prd_content}\n"
        )
        if revision_mode:
            user_prompt += "\n=== REVISION MODE ===\n"
            user_prompt += "You are updating and revising your previous system architecture design based on critique/issues raised by the QA Reviewer.\n"
            if previous_architecture:
                user_prompt += f"\nPrevious System Architecture Design:\n{previous_architecture}\n"
            if reviewer_issues:
                user_prompt += "\nCritique / Issues to address:\n"
                for issue in reviewer_issues:
                    user_prompt += f"- {issue}\n"
            if reviewer_recommendations:
                user_prompt += "\nQA Recommendations to incorporate:\n"
                for rec in reviewer_recommendations:
                    user_prompt += f"- {rec}\n"
            user_prompt += "\nPlease produce a revised system architecture JSON addressing all of the above issues and recommendations."

        if debate_history:
            user_prompt += "\nHere is the critique/feedback you must incorporate:\n"
            for turn in debate_history:
                if turn.get("agent_name") == "Critic":
                    user_prompt += f"- Critique: {turn.get('content')}\n"
            user_prompt += "\nGenerate an updated version of the architectural design JSON incorporating this feedback."

        retries = 2
        last_error = None
        for attempt in range(retries):
            try:
                import inspect
                sig = inspect.signature(self.llm_provider.generate)
                if "response_schema" in sig.parameters:
                    response_str = await self.llm_provider.generate(system_prompt, user_prompt, response_schema=ArchitectOutput)
                else:
                    response_str = await self.llm_provider.generate(system_prompt, user_prompt)
                cleaned_str = self._clean_json_string(response_str)
                # Validate with Pydantic
                architect_output = ArchitectOutput.model_validate_json(cleaned_str)
                return architect_output
            except Exception as e:
                last_error = e
                logger.warning(f"Architect agent generation/validation failed on attempt {attempt + 1}: {e}")
                if attempt == 0:
                    user_prompt += f"\n\nCorrection from previous attempt: Your last response failed validation with error: {str(e)}. Please output valid JSON matching the schema strictly without extra markdown formatting."

        raise ValueError(f"Failed to generate valid Architect output after {retries} attempts. Last error: {str(last_error)}")

    def _clean_json_string(self, text: str) -> str:
        text = text.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()
        return text

    def format_architecture(self, output: ArchitectOutput) -> str:
        stack_md = "\n".join([f"- {item}" for item in output.recommended_stack])
        components_md = "\n".join([f"- {comp}" for comp in output.system_components])
        tradeoffs_md = "\n".join([f"- {trade}" for trade in output.tradeoffs])
        scalability_md = "\n".join([f"- {scale}" for scale in output.scalability_considerations])
        risks_md = "\n".join([f"- {risk}" for risk in output.risks])
        
        return f"""# System Architecture Design

## 1. Executive Summary
{output.executive_summary}

## 2. Architecture Overview
{output.architecture_overview}

## 3. Recommended Technology Stack
{stack_md}

## 4. Key System Components
{components_md}

## 5. Architectural Tradeoffs
{tradeoffs_md}

## 6. Scalability & Performance considerations
{scalability_md}

## 7. Risks & Mitigations
{risks_md}

---
*Confidence Score: {output.confidence:.2f}*
"""

    def format_database(self, output: ArchitectOutput) -> str:
        db_md = "\n".join([f"- {entity}" for entity in output.database_design])
        return f"""# Database Design & Normalization

## Schema Definitions & Entities
{db_md}
"""

    def format_api(self, output: ArchitectOutput) -> str:
        api_md = "\n".join([f"- {contract}" for contract in output.api_design])
        return f"""# API Structure & Contracts

## Endpoints and Specifications
{api_md}
"""
