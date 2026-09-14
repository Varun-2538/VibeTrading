from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn

# Import controllers
from controllers import strategy_router, ohlc_router, websocket_router
from controllers.chat_controller import router as chat_router

# Import services and database
from models.database import db
from services.cache_service import cache_service
from mcp_server.client import mcp_client
from config.settings import settings
from data_ingestion.crypto_scheduler import crypto_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events
    """
    # Startup
    print("Starting TradeSmart.AI Backend...")

    # Connect to database
    try:
        await db.connect()
        print("[OK] Connected to Supabase/PostgreSQL")
    except Exception as e:
        print(f"[ERROR] Database connection failed: {e}")

    # Connect to Redis
    try:
        await cache_service.connect()
        print("[OK] Connected to Redis")
    except Exception as e:
        print(f"[WARNING] Redis connection failed: {e} (Optional service)")

    # Connect to MCP server
    try:
        await mcp_client.connect()
        print("[OK] Connected to MCP Server")
    except Exception as e:
        print(f"[WARNING] MCP connection failed: {e} (Will fix MCP server API later)")

    print(f"[OK] Backend running on port {settings.backend_port}")
    print(f"[OK] CORS enabled for: {settings.frontend_url}")

    # Start crypto data scheduler for live updates
    try:
        await crypto_scheduler.start()
        print("[OK] Crypto scheduler started - Live Binance data every 5 min")
    except Exception as e:
        print(f"[WARNING] Crypto scheduler failed: {e}")

    yield

    # Shutdown
    print("Shutting down TradeSmart.AI Backend...")

    # Stop crypto scheduler
    try:
        await crypto_scheduler.stop()
        print("[OK] Crypto scheduler stopped")
    except Exception as e:
        print(f"[ERROR] Crypto scheduler stop failed: {e}")

    # Disconnect from services
    try:
        await db.disconnect()
        print("[OK] Disconnected from database")
    except Exception as e:
        print(f"[ERROR] Database disconnect failed: {e}")

    try:
        await cache_service.disconnect()
        print("[OK] Disconnected from Redis")
    except Exception as e:
        print(f"[ERROR] Redis disconnect failed: {e}")

    try:
        await mcp_client.disconnect()
        print("[OK] Disconnected from MCP Server")
    except Exception as e:
        print(f"[ERROR] MCP disconnect failed: {e}")

    print("[OK] Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="TradeSmart.AI API",
    description="AI-powered trading strategy builder using Cerebras LLMs and MCP",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:3000", "*"],  # Update in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(strategy_router)
app.include_router(ohlc_router)
app.include_router(websocket_router)
app.include_router(chat_router)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "TradeSmart.AI API",
        "version": "1.0.0",
        "status": "operational",
        "docs": "/docs",
        "features": [
            "AI-powered strategy building",
            "Real-time market data",
            "Technical indicators (RSI, MACD, EMA)",
            "Liquidation level detection",
            "Chart annotations",
            "WebSocket support"
        ]
    }


@app.get("/health")
async def health_check():
    """Global health check"""
    return {
        "status": "healthy",
        "services": {
            "api": "operational",
            "database": "connected" if db.pool else "disconnected",
            "cache": "connected" if cache_service.redis_client else "disconnected",
            "mcp": "connected" if mcp_client.session else "disconnected"
        }
    }


@app.get("/api/config")
async def get_config():
    """Get public configuration"""
    return {
        "timeframes": ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
        "supported_symbols": ["BTC/USD", "ETH/USD", "SOL/USD"],  # Extend as needed
        "max_lookback_periods": 1000,
        "websocket_endpoints": [
            "/ws/{symbol}",
            "/ws/strategy/{symbol}"
        ]
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.backend_port,
        reload=True,
        log_level="info"
    )
