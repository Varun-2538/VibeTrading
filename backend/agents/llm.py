from langchain_openai import ChatOpenAI

from config.settings import settings


def make_llm(temperature: float, max_tokens: int) -> ChatOpenAI:
    """Chat model for the agents, pointed at whichever provider .env configures."""
    return ChatOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
