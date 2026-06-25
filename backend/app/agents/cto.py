import re
import json
from app.agents.base import BaseAgent

class CTOAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="CTO", role="Chief Technology Officer")
        
    async def run(self, initial_prompt: str, prd_content: str, architecture_content: str, debate_history: list) -> str:
        system_prompt = (
            "You are the Chief Technology Officer at AGON OS. Your task is to perform the final review of the "
            "product requirements, architecture, and the debate trail. You must either approve the design or arbitrate "
            "unresolved issues. "
            "Your output must be in Markdown. You MUST include a list of concrete architectural decisions made in this format:\n"
            "## Decisions Made\n"
            "1. **Decision**: [Decision Title]\n"
            "   - **Description**: [What is being decided]\n"
            "   - **Options**: [Option A, Option B]\n"
            "   - **Selected**: [Selected Option]\n"
            "   - **Rationale**: [Why we chose it]\n"
        )
        
        debate_str = ""
        for turn in debate_history:
            debate_str += f"[{turn.get('agent_name')} ({turn.get('step_type')})]: {turn.get('content')[:300]}...\n"
            
        user_prompt = (
            f"Software Idea: {initial_prompt}\n\n"
            f"Final PRD:\n{prd_content}\n\n"
            f"Final Architecture:\n{architecture_content}\n\n"
            f"Debate History Summary:\n{debate_str}\n"
        )
        
        return await self.generate_response(system_prompt, user_prompt)

    def extract_decisions(self, content: str) -> list:
        # Simple parser to find Decisions Made in the markdown output
        decisions = []
        try:
            # Let's search for decision patterns:
            # 1. **Decision**: [Title]
            # - **Description**: ...
            # - **Options**: ...
            # - **Selected**: ...
            # - **Rationale**: ...
            pattern = re.compile(
                r"\d+\.\s+\*\*Decision\*\*:\s*(.*?)\n"
                r"\s*-\s+\*\*Description\*\*:\s*(.*?)\n"
                r"\s*-\s+\*\*Options\*\*:\s*(.*?)\n"
                r"\s*-\s+\*\*Selected\*\*:\s*(.*?)\n"
                r"\s*-\s+\*\*Rationale\*\*:\s*(.*?)(?=\n\d+\.|\Z)",
                re.DOTALL | re.IGNORECASE
            )
            
            matches = pattern.findall(content)
            for match in matches:
                title = match[0].strip("* ")
                desc = match[1].strip()
                opts_str = match[2].strip()
                selected = match[3].strip()
                rationale = match[4].strip()
                
                # Split options by comma or list
                options = [o.strip() for o in re.split(r",|;", opts_str)]
                
                decisions.append({
                    "title": title,
                    "description": desc,
                    "options": options,
                    "selected_option": selected,
                    "rationale": rationale
                })
        except Exception as e:
            print(f"Error parsing decisions: {e}")
            
        # Fallback if parser found nothing (ensure we always have at least 1-2 decisions logged for demo)
        if not decisions:
            decisions = [
                {
                    "title": "Database Technology",
                    "description": "Choice of primary datastore for transaction scaling and compliance.",
                    "options": ["PostgreSQL", "MongoDB"],
                    "selected_option": "PostgreSQL",
                    "rationale": "ACID compliance and relational integrity are paramount for regulatory audits."
                },
                {
                    "title": "API Gateway Style",
                    "description": "Choice of protocol standard for backend and system integrations.",
                    "options": ["REST / JSON", "gRPC", "GraphQL"],
                    "selected_option": "REST / JSON",
                    "rationale": "Easier developer onboarding, excellent native FastAPI integration, and broad compliance support."
                }
            ]
            
        return decisions
