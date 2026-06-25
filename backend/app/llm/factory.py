from app.llm.base import LLMProvider
from app.llm.providers.gemini import GeminiProvider
from app.llm.providers.mock import MockLLMProvider
from app.config import settings

class LLMFactory:
    @staticmethod
    def get_provider() -> LLMProvider:
        if getattr(settings, "USE_MOCK_LLM", True):
            return MockLLMProvider()
        
        api_key = getattr(settings, "GEMINI_API_KEY", None)
        model = getattr(settings, "GEMINI_MODEL", "gemini-1.5-flash")
        return GeminiProvider(api_key=api_key, model=model)
