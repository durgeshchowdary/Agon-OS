import json
import logging
import re
from app.agents.base import BaseAgent
from app.llm.factory import LLMFactory
from app.schemas.codegen import CodegenOutput

logger = logging.getLogger(__name__)

class CodegenAgent(BaseAgent):
    def __init__(self, llm_provider=None):
        super().__init__(name="CodeGenerator", role="Code Generator")
        self.llm_provider = llm_provider or LLMFactory.get_provider()

    async def run(
        self,
        prd_content: str,
        architecture_content: str,
        database_content: str,
        api_content: str,
        backlog_content: str,
        debate_history: list = None,
        db = None
    ) -> CodegenOutput:
        existing_info = ""
        if db:
            try:
                from sqlalchemy.future import select
                from app.models.repo_intel import RepoRoute, RepoClass, RepoFunction
                
                routes_res = await db.execute(select(RepoRoute))
                routes = routes_res.scalars().all()
                
                classes_res = await db.execute(select(RepoClass))
                classes = classes_res.scalars().all()
                
                funcs_res = await db.execute(select(RepoFunction).where(RepoFunction.class_name == None))
                funcs = funcs_res.scalars().all()
                
                existing_info += "\nEXISTING ROUTERS, CLASSES, AND SERVICES FOUND IN CODEBASE:\n"
                existing_info += "API Routes:\n"
                for r in routes:
                    existing_info += f"- {r.http_method} {r.route_path} (Handler: {r.handler} in {r.file_path})\n"
                existing_info += "\nClasses:\n"
                for c in classes:
                    existing_info += f"- Class {c.class_name} (in {c.file_path})\n"
                existing_info += "\nTop-level Functions:\n"
                for f in funcs:
                    existing_info += f"- Function {f.function_name} (in {f.file_path})\n"
            except Exception as e:
                logger.warning(f"Failed to fetch repository index for duplicate checking: {e}")

        system_prompt = (
            "You are the Principal Software Engineer at AGON OS. Your task is to analyze the "
            "Product Requirements (PRD), Architecture Design, Database Design, API Contracts, and the approved Backlog "
            "to generate the complete task-by-task engineering implementation plan and target source files.\n\n"
            "CRITICAL RULES:\n"
            "- You must write complete, functional, production-ready code files. No stub implementations or 'TODO' placeholders.\n"
            "- REUSE & DUPLICATE PREVENTION RULES:\n"
            "  * Review the 'EXISTING ROUTERS, CLASSES, AND SERVICES' list carefully.\n"
            "  * Do not duplicate existing classes, functions, routes, or services. If equivalent business logic exists, import and extend it.\n"
            "  * Recommend extension over duplication, and explain your reuse reasoning in the implementation plan.\n"
            "- Generate the code task-by-task as planned in the backlog.\n"
            "- Generate associated unit/integration tests, documentation, and migration scripts if required.\n"
            "- Keep all paths relative to the workspace root (e.g. backend/app/api/v1/billing.py).\n\n"
            "You MUST output your response as a valid JSON object matching this schema:\n"
            "{\n"
            "  \"implementation_plan\": \"Markdown text describing the step-by-step code changes and reuse reasoning\",\n"
            "  \"files\": [\n"
            "    {\n"
            "      \"path\": \"backend/app/api/v1/billing.py\",\n"
            "      \"content\": \"class BillingEngine:...\",\n"
            "      \"type\": \"code\"\n"
            "    }\n"
            "  ],\n"
            "  \"confidence\": 0.95\n"
            "}\n"
            "Do not include any explanation, markdown formatting (like ```json), or additional text outside the JSON structure."
        )

        user_prompt = (
            f"Requirements (PRD):\n{prd_content}\n\n"
            f"System Architecture Design:\n{architecture_content}\n\n"
            f"Database Design:\n{database_content}\n\n"
            f"API Structure & Contracts:\n{api_content}\n\n"
            f"Approved Engineering Backlog:\n{backlog_content}\n\n"
        )
        if existing_info:
            user_prompt += f"{existing_info}\n"
            
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
                    response_str = await self.llm_provider.generate(system_prompt, user_prompt, response_schema=CodegenOutput)
                else:
                    response_str = await self.llm_provider.generate(system_prompt, user_prompt)
                
                cleaned_str = self._clean_json_string(response_str)
                codegen_output = CodegenOutput.model_validate_json(cleaned_str)
                return codegen_output
            except Exception as e:
                last_error = e
                logger.warning(f"Codegen agent generation failed on attempt {attempt + 1}: {e}")
                if attempt == 0:
                    user_prompt += f"\n\nCorrection from previous attempt: Your last response failed validation with error: {str(e)}. Please output valid JSON matching the schema strictly."
 
        raise ValueError(f"Failed to generate valid Codegen output after {retries} attempts. Last error: {str(last_error)}")

    def _clean_json_string(self, text: str) -> str:
        text = text.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()
        return text
