import os
from dotenv import load_dotenv

load_dotenv()

OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")
OLLAMA_TIMEOUT: int = int(os.getenv("OLLAMA_TIMEOUT", "25"))
OLLAMA_RATE_LIMIT: int = int(os.getenv("OLLAMA_RATE_LIMIT_PER_MINUTE", "20"))
MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///alerts.db")
