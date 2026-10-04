from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # LLM - any OpenAI-compatible endpoint (Groq, Cerebras, OpenAI, ...)
    llm_api_key: str
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "openai/gpt-oss-120b"

    # Database
    database_url: str
    timescale_host: str = "localhost"
    timescale_port: int = 5432
    timescale_db: str = "tradesmart"
    timescale_user: str
    timescale_password: str

    # Postgres pool, per process. Three processes share one database - the API,
    # the backtest worker and (later) the executor - and Postgres defaults to 100
    # connections, so a background process that only polls asks for far fewer
    # than the API, which serves every request and every socket.
    db_pool_min: int = 5
    db_pool_max: int = 20

    # Redis
    redis_url: str = "redis://localhost:6379"

    # API Keys
    binance_api_key: Optional[str] = None
    binance_api_secret: Optional[str] = None

    # Session signing. Deliberately has no default: a guessable secret here lets
    # anyone mint a token for any wallet address, so a deploy that forgot to set
    # it must fail at boot rather than run in that state.
    jwt_secret: str

    # App Config
    frontend_url: str = "http://localhost:3000"
    backend_port: int = 8000

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
