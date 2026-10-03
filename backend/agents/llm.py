from typing import Optional

from langchain_openai import ChatOpenAI

from config.settings import settings


def make_llm(
    temperature: float,
    max_tokens: int,
    reasoning_effort: Optional[str] = None,
    **extra,
) -> ChatOpenAI:
    """
    Chat model for the agents, pointed at whichever provider .env configures.

    `extra` is passed straight to the provider as request fields - for example
    response_format or reasoning_effort - so a caller that needs them does not
    have to build its own client.
    """
    return ChatOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        temperature=temperature,
        max_tokens=max_tokens,
        # A first-class parameter in langchain-openai; passing it through
        # model_kwargs works but warns on every call.
        reasoning_effort=reasoning_effort,
        model_kwargs=extra,
    )
