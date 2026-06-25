class LLMProvider:
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema = None
    ) -> str:
        """
        Generates content from the LLM based on system and user prompts.
        """
        raise NotImplementedError
