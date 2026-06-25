import json
import logging
import re
from pydantic import BaseModel
from app.agents.base import BaseAgent
from app.llm.factory import LLMFactory

logger = logging.getLogger(__name__)

class PMOutput(BaseModel):
    summary: str
    requirements: list[str]
    user_stories: list[str]
    risks: list[str]
    decisions: list[str]
    confidence: float

class PMAgent(BaseAgent):
    def __init__(self, llm_provider=None):
        super().__init__(name="PM", role="Product Manager")
        self.llm_provider = llm_provider or LLMFactory.get_provider()
        
    async def run(self, initial_prompt: str, debate_history: list = None, memory_context = None) -> PMOutput:
        system_prompt = (
            "You are the Lead Product Manager at AGON OS. Convert the user prompt into product requirements, "
            "generate user stories, identify risks, identify major decisions, and estimate complexity.\n\n"
            "CRITICAL RULES:\n"
            "- You must NOT generate architecture or code.\n"
            "- You must stay strictly within product management scope.\n\n"
            "You MUST output your response as a valid JSON object matching this schema:\n"
            "{\n"
            "  \"summary\": \"A high-level summary of the product\",\n"
            "  \"requirements\": [\"Requirement 1\", \"Requirement 2\", ...],\n"
            "  \"user_stories\": [\"User Story 1\", \"User Story 2\", ...],\n"
            "  \"risks\": [\"Risk 1\", \"Risk 2\", ...],\n"
            "  \"decisions\": [\"Decision 1\", \"Decision 2\", ...],\n"
            "  \"confidence\": 0.95\n"
            "}\n"
            "Do not include any explanation, markdown formatting (like ```json), or additional text outside the JSON structure."
        )
        
        user_prompt = f"Software Idea: {initial_prompt}\n"
        if memory_context and (memory_context.summary or memory_context.previous_requirements):
            user_prompt += "\n=== PROJECT HISTORY & MEMORY ===\n"
            if memory_context.summary:
                user_prompt += f"Summary of Previous Iterations:\n{memory_context.summary}\n"
            if memory_context.previous_decisions:
                user_prompt += "Previous Product/Architecture Decisions:\n"
                for dec in memory_context.previous_decisions:
                    user_prompt += f"- {dec}\n"
            user_prompt += "Please build upon this history and keep requirements aligned with previous iterations.\n"

        if debate_history:
            user_prompt += "\nHere is the critique/feedback you must incorporate:\n"
            for turn in debate_history:
                if turn.get("agent_name") == "Critic":
                    user_prompt += f"- Critique: {turn.get('content')}\n"
            user_prompt += "\nGenerate an updated version of the JSON incorporating this feedback."

        retries = 2
        last_error = None
        for attempt in range(retries):
            try:
                import inspect
                sig = inspect.signature(self.llm_provider.generate)
                if "response_schema" in sig.parameters:
                    response_str = await self.llm_provider.generate(system_prompt, user_prompt, response_schema=PMOutput)
                else:
                    response_str = await self.llm_provider.generate(system_prompt, user_prompt)
                cleaned_str = self._clean_json_string(response_str)
                # Validate with Pydantic
                pm_output = PMOutput.model_validate_json(cleaned_str)
                return pm_output
            except Exception as e:
                last_error = e
                logger.warning(f"PM agent generation/validation failed on attempt {attempt + 1}: {e}")
                if attempt == 0:
                    # Provide hints for validation retry
                    user_prompt += f"\n\nCorrection from previous attempt: Your last response failed validation with error: {str(e)}. Please output valid JSON matching the schema strictly without extra markdown formatting."

        # If we reach here, validation failed on all attempts
        raise ValueError(f"Failed to generate valid PM output after {retries} attempts. Last error: {str(last_error)}")

    def _clean_json_string(self, text: str) -> str:
        text = text.strip()
        # Remove markdown code block syntax if present
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()
        return text

    def format_to_markdown(self, pm_output: PMOutput) -> str:
        """
        Formats the validated PMOutput Pydantic model into a clean Markdown string.
        """
        requirements_md = "\n".join([f"- {req}" for req in pm_output.requirements])
        stories_md = "\n".join([f"- {story}" for story in pm_output.user_stories])
        risks_md = "\n".join([f"- {risk}" for risk in pm_output.risks])
        decisions_md = "\n".join([f"- {decision}" for decision in pm_output.decisions])

        markdown = f"""# Product Requirements Document (PRD)

## 1. Executive Summary
{pm_output.summary}

## 2. Core Functional Requirements
{requirements_md}

## 3. User Stories
{stories_md}

## 4. Risks & Mitigations
{risks_md}

## 5. Key Product Decisions
{decisions_md}

---
*Confidence Score: {pm_output.confidence:.2f}*
"""
        return markdown
