from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).resolve().parent / "prompts"


@lru_cache(maxsize=None)
def load(name: str) -> str:
    """Prompt text shared by every provider (openai, anthropic, ollama): app/modules/llm/prompts/<name>.md."""
    return (_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
