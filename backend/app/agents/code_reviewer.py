import json
import logging
import re
from app.agents.base import BaseAgent
from app.llm.factory import LLMFactory
from app.schemas.code_reviewer import CodeReviewOutput

logger = logging.getLogger(__name__)

class CodeReviewAgent(BaseAgent):
    def __init__(self, llm_provider=None):
        super().__init__(name="CodeReviewer", role="Code Reviewer")
        self.llm_provider = llm_provider or LLMFactory.get_provider()

    async def run(
        self,
        prd_content: str,
        architecture_content: str,
        backlog_content: str,
        generated_files_content: str,
        existing_codebase_indices: str
    ) -> CodeReviewOutput:
        system_prompt = (
            "You are the Automated Code Reviewer and QA Specialist at AGON OS.\n"
            "Your task is to analyze the proposed generated files against the Approved Requirements (PRD), Approved Architecture, Approved Backlog, and the list of existing codebase indices.\n\n"
            "CRITICAL REVIEW CRITERIA:\n"
            "1. Architecture Compliance: Verify that new routes, classes, or models strictly match the names and structures approved in the System Architecture and Database specifications.\n"
            "2. Repository Reuse (Duplication): Cross-reference existing routes and classes. If the proposed code recreates code/methods already present, raise a duplication finding suggesting imports.\n"
            "3. Security Review (Heuristics): Heuristically scan for dangerous functions (eval, exec), raw unparameterized SQL executes, hardcoded secrets, or path traversals. These are heuristic findings, not absolute security guarantees.\n"
            "4. Test Coverage Review: Verify if tests are present or defined in the proposed artifacts. Be flexible: test coverage detection is artifact-based; look for tests within the proposed plan or generated files, rather than relying strictly on file patterns.\n"
            "5. Maintainability Review: Check for excessive complexity, long functions (>50 lines), poor naming conventions, or lack of docstrings.\n"
            "6. Dependency Review: Watch out for unnecessary or circular imports.\n\n"
            "PASS/WARNING/FAIL DECISION RULES:\n"
            "- FAIL: Any finding with Critical or High severity is present.\n"
            "- WARNING: No Critical/High findings, but one or more Medium severity findings are present.\n"
            "- PASS: Only Low severity findings or no findings are present.\n\n"
            "SCORING RULE (Starting at 100.0, deduct points for findings, min score is 0.0):\n"
            "- Critical finding: -30.0 points\n"
            "- High finding: -15.0 points\n"
            "- Medium finding: -5.0 points\n"
            "- Low finding: -2.0 points\n\n"
            "You MUST output your response as a valid JSON object matching this schema:\n"
            "{\n"
            "  \"status\": \"FAIL | WARNING | PASS\",\n"
            "  \"summary\": \"Executive summary of the review findings and compliance\",\n"
            "  \"score\": 85.0,\n"
            "  \"findings\": [\n"
            "    {\n"
            "      \"category\": \"Architecture | Security | Duplication | Tests | Maintainability | Dependencies\",\n"
            "      \"severity\": \"Critical | High | Medium | Low\",\n"
            "      \"file_path\": \"backend/app/api/v1/billing.py\",\n"
            "      \"line_number\": 12,\n"
            "      \"finding_title\": \"Duplicate route definition\",\n"
            "      \"description\": \"Route POST /api/v1/payments is already defined in backend/app/api/v1/payments.py\",\n"
            "      \"recommendation\": \"Extend backend/app/api/v1/payments.py instead of creating a new router.\"\n"
            "    }\n"
            "  ],\n"
            "  \"confidence\": 0.95\n"
            "}\n"
            "Do not include any explanation, markdown formatting (like ```json), or additional text outside the JSON structure."
        )

        user_prompt = (
            f"Requirements (PRD):\n{prd_content}\n\n"
            f"System Architecture Design:\n{architecture_content}\n\n"
            f"Approved Backlog:\n{backlog_content}\n\n"
            f"Proposed Generated Files:\n{generated_files_content}\n\n"
            f"Existing Codebase Indices:\n{existing_codebase_indices}\n\n"
        )

        retries = 2
        last_error = None
        for attempt in range(retries):
            try:
                import inspect
                sig = inspect.signature(self.llm_provider.generate)
                if "response_schema" in sig.parameters:
                    response_str = await self.llm_provider.generate(system_prompt, user_prompt, response_schema=CodeReviewOutput)
                else:
                    response_str = await self.llm_provider.generate(system_prompt, user_prompt)
                
                cleaned_str = self._clean_json_string(response_str)
                review_output = CodeReviewOutput.model_validate_json(cleaned_str)
                return review_output
            except Exception as e:
                last_error = e
                logger.warning(f"CodeReviewer agent generation failed on attempt {attempt + 1}: {e}")
                if attempt == 0:
                    user_prompt += f"\n\nCorrection from previous attempt: Your last response failed validation with error: {str(e)}. Please output valid JSON matching the schema strictly."

        raise ValueError(f"Failed to generate valid CodeReviewer output after {retries} attempts. Last error: {str(last_error)}")

    def _clean_json_string(self, text: str) -> str:
        text = text.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()
        return text
