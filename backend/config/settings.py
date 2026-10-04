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

    # The address the executor signs with, published by /api/execution/account so a
    # vault owner grants permission to the right operator. Empty until an executor
    # key exists, and the panel refuses to offer a grant while it is.
    executor_address: str = ""

    # The key itself. Empty is a normal state: shadow mode needs none, and an
    # executor without one idles rather than refusing to start. What limits the
    # damage if it leaks is the vault - it can swap inside a contract the owner
    # controls, within their caps, and has no path to withdraw - not this variable.
    # A KMS signer implements the same interface and is what should sign against
    # mainnet; see services/execution/signer.py.
    executor_private_key: str = ""

    # Where each chain is, and where its factory went. Public endpoints are the
    # default because they need no account; every read retries and every send is
    # asked about by hash rather than retried, which is what makes a rate-limited
    # node survivable. Chain ids, tokens and feeds are not settings - they live in
    # services/execution/markets.py, pinned to contracts/src/Addresses.sol.
    #
    # A chain with no factory address is a chain live mode refuses, not one it
    # guesses at. Same key signs on both: an EOA is an address on every EVM chain.
    arbitrum_rpc_url: str = "https://arb1.arbitrum.io/rpc"
    arbitrum_vault_factory_address: str = ""
    robinhood_rpc_url: str = "https://rpc.mainnet.chain.robinhood.com"
    robinhood_vault_factory_address: str = ""

    # App Config
    frontend_url: str = "http://localhost:3000"
    backend_port: int = 8000

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
