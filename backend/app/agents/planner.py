import json
import logging
import re
from app.agents.base import BaseAgent
from app.llm.factory import LLMFactory
from app.schemas.planner import PlannerOutput

logger = logging.getLogger(__name__)

class PlannerAgent(BaseAgent):
    def __init__(self, llm_provider=None):
        super().__init__(name="Planner", role="Task Planner")
        self.llm_provider = llm_provider or LLMFactory.get_provider()

    async def run(
        self,
        prd_content: str,
        architecture_content: str,
        database_content: str,
        api_content: str,
        debate_history: list = None
    ) -> PlannerOutput:
        system_prompt = (
            "You are the Lead Software Architect & Engineering Planner at AGON OS. Your task is to analyze the "
            "Product Requirements Document (PRD), System Architecture Design, Database Design, and API Contracts "
            "to generate a complete and structured engineering backlog.\n\n"
            "CRITICAL RULES:\n"
            "- You must organize the backlog strictly in a three-tier hierarchy: Epic -> Tasks -> Subtasks.\n"
            "- Do not write system design documentations or actual code implementation.\n"
            "- Focus purely on concrete, actionable engineering tasks.\n\n"
            "You MUST output your response as a valid JSON object matching this schema:\n"
            "{\n"
            "  \"epic_title\": \"High-level title for the implementation phase\",\n"
            "  \"epic_description\": \"Detailed description of the epic objective\",\n"
            "  \"tasks\": [\n"
            "    {\n"
            "      \"id\": \"TASK-101\",\n"
            "      \"title\": \"Task Title\",\n"
            "      \"description\": \"Detailed description of the task objective\",\n"
            "      \"complexity\": \"High/Medium/Low\",\n"
            "      \"priority\": \"Critical/High/Medium/Low\",\n"
            "      \"estimate\": \"Estimate in story points or days (e.g. 3 story points)\",\n"
            "      \"dependencies\": [\"DEPENDENCY-ID-1\", ...],\n"
            "      \"acceptance_criteria\": [\"Criteria 1\", \"Criteria 2\"],\n"
            "      \"subtasks\": [\n"
            "        {\n"
            "          \"id\": \"SUB-101a\",\n"
            "          \"title\": \"Subtask Title\",\n"
            "          \"description\": \"Description of subtask work\",\n"
            "          \"complexity\": \"High/Medium/Low\",\n"
            "          \"priority\": \"High/Medium/Low\",\n"
            "          \"estimate\": \"Estimate (e.g. 1 story point)\",\n"
            "          \"dependencies\": [],\n"
            "          \"acceptance_criteria\": [\"Criteria 1\"]\n"
            "        }\n"
            "      ]\n"
            "    }\n"
            "  ],\n"
            "  \"confidence\": 0.95\n"
            "}\n"
            "Do not include any explanation, markdown formatting (like ```json), or additional text outside the JSON structure."
        )

        user_prompt = (
            f"PRD Requirements:\n{prd_content}\n\n"
            f"System Architecture Design:\n{architecture_content}\n\n"
            f"Database Design:\n{database_content}\n\n"
            f"API Structure & Contracts:\n{api_content}\n\n"
        )
        if debate_history:
            user_prompt += "\nDebate feedback to incorporate:\n"
            for turn in debate_history:
                user_prompt += f"- [{turn.get('agent_name')}]: {turn.get('content')}\n"

        retries = 2
        last_error = None
        for attempt in range(retries):
            try:
                import inspect
                sig = inspect.signature(self.llm_provider.generate)
                if "response_schema" in sig.parameters:
                    response_str = await self.llm_provider.generate(system_prompt, user_prompt, response_schema=PlannerOutput)
                else:
                    response_str = await self.llm_provider.generate(system_prompt, user_prompt)
                
                cleaned_str = self._clean_json_string(response_str)
                planner_output = PlannerOutput.model_validate_json(cleaned_str)
                return planner_output
            except Exception as e:
                last_error = e
                logger.warning(f"Planner agent generation failed on attempt {attempt + 1}: {e}")
                if attempt == 0:
                    user_prompt += f"\n\nCorrection from previous attempt: Your last response failed validation with error: {str(e)}. Please output valid JSON matching the schema strictly."

        raise ValueError(f"Failed to generate valid Planner output after {retries} attempts. Last error: {str(last_error)}")

    def _clean_json_string(self, text: str) -> str:
        text = text.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()
        return text

    def format_to_markdown(self, output: PlannerOutput) -> str:
        md = f"# Engineering Backlog: {output.epic_title}\n\n"
        md += f"**Objective:** {output.epic_description}\n\n"
        md += "## Tasks Breakdown\n\n"
        for t in output.tasks:
            md += f"### [{t.id}] {t.title}\n"
            md += f"* **Complexity:** {t.complexity} | **Priority:** {t.priority} | **Estimate:** {t.estimate}\n"
            if t.dependencies:
                md += f"* **Dependencies:** {', '.join(t.dependencies)}\n"
            md += f"\n**Description:** {t.description}\n\n"
            if t.acceptance_criteria:
                md += "**Acceptance Criteria:**\n"
                for ac in t.acceptance_criteria:
                    md += f"- {ac}\n"
                md += "\n"
            if t.subtasks:
                md += "**Subtasks:**\n"
                for st in t.subtasks:
                    md += f"- **[{st.id}] {st.title}** ({st.estimate}) - {st.description}\n"
                md += "\n"
            md += "---\n\n"
        md += f"*Confidence Score: {output.confidence:.2f}*\n"
        return md
