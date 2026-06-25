import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "AGON OS"
    API_V1_STR: str = "/api/v1"
    
    # Security
    JWT_SECRET: str = os.getenv("JWT_SECRET", "supersecretkeyforagonosv1developmentonly")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    
    # Database
    # Use SQLite async driver as default for easy running, support Postgresql overrides
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./agon_os.db")
    
    # Agent Ollama config
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen3.5:latest")
    
    # Debate configuration
    MAX_DEBATE_ROUNDS: int = int(os.getenv("MAX_DEBATE_ROUNDS", "2"))

    # Gemini configuration
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    USE_MOCK_LLM: bool = os.getenv("USE_MOCK_LLM", "true").lower() in ("true", "1", "yes")

    class Config:
        case_sensitive = True

settings = Settings()
