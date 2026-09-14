# TradeSmart.AI Backend

AI-powered trading strategy builder using Cerebras LLMs, MCP (Model Context Protocol), and FastAPI.

## 🏗️ Architecture

```
backend/
├── main.py                 # FastAPI application entry point
├── config/                 # Configuration & settings
├── models/                 # Data models & database
│   ├── database.py        # TimescaleDB connection
│   └── schemas.py         # Pydantic models
├── repositories/           # Data access layer
│   ├── ohlc_repository.py
│   └── annotation_repository.py
├── services/              # Business logic layer
│   ├── cache_service.py   # Redis caching
│   ├── market_data_service.py
│   └── strategy_service.py
├── mcp/                   # MCP server & tools
│   ├── server.py          # MCP server
│   ├── client.py          # MCP client
│   └── tools/             # MCP tools
│       ├── ohlc_tool.py
│       ├── indicator_tool.py
│       ├── liquidation_tool.py
│       ├── annotation_tool.py
│       └── strategy_tool.py
├── agents/                # AI agents (Cerebras)
│   ├── orchestrator.py    # Master coordinator
│   ├── liquidation_agent.py
│   └── indicator_agent.py
├── controllers/           # API routes
│   ├── strategy_controller.py
│   ├── ohlc_controller.py
│   └── websocket_controller.py
└── utils/                 # Helper utilities
```

## 🚀 Features

- **AI-Powered Strategy Building**: Uses Cerebras Llama 3.1 70B for orchestration
- **Multi-Agent System**:
  - Orchestrator Agent (coordination)
  - Liquidation Agent (support/resistance detection)
  - Indicator Agent (technical analysis)
- **MCP Integration**: 6 specialized tools for market analysis
- **Real-time Updates**: WebSocket support for live data
- **Technical Indicators**: RSI, MACD, EMA calculations
- **Liquidation Detection**: Advanced support/resistance analysis
- **Chart Annotations**: Auto-generated visual markers
- **Redis Caching**: High-performance data caching

## 📋 Prerequisites

- Python 3.10+
- PostgreSQL with TimescaleDB extension
- Redis
- Cerebras API key

## 🔧 Setup

1. **Install dependencies**:
```bash
pip install -r requirements.txt
```

2. **Configure environment**:
```bash
cp .env.example .env
# Edit .env with your credentials
```

3. **Setup database** (see database setup guide in plan.md):
```sql
CREATE EXTENSION IF NOT EXISTS timescaledb;
-- Run schema from plan.md
```

4. **Run the server**:
```bash
python main.py
```

Server will start on `http://localhost:8000`

## 📡 API Endpoints

### Strategy Building
- `POST /api/strategy/build` - Build trading strategy from prompt
- `GET /api/strategy/analyze/{symbol}` - Quick market analysis

### Market Data
- `GET /api/ohlc/{symbol}` - Fetch OHLC data
- `GET /api/price/{symbol}` - Get latest price
- `GET /api/indicators/{symbol}` - Calculate indicators
- `GET /api/liquidation-levels/{symbol}` - Detect levels
- `GET /api/market-summary/{symbol}` - Complete summary

### Annotations
- `GET /api/annotations/{symbol}` - Get chart annotations
- `DELETE /api/annotations/{symbol}` - Clear annotations

### WebSocket
- `WS /ws/{symbol}` - Real-time market data stream
- `WS /ws/strategy/{symbol}` - Strategy signals stream

## 🤖 AI Agents

### Orchestrator Agent
- Model: Llama 3.1 70B
- Role: Coordinates specialized agents and synthesizes strategies
- Temperature: 0.7 (creative)

### Liquidation Agent
- Model: Llama 3.1 8B
- Role: Detects support/resistance and liquidation zones
- Temperature: 0.3 (deterministic)

### Indicator Agent
- Model: Llama 3.1 8B
- Role: Analyzes RSI, MACD, EMA indicators
- Temperature: 0.3 (deterministic)

## 🛠️ MCP Tools

1. **get_ohlc_data** - Fetch candlestick data
2. **calculate_indicators** - Compute technical indicators
3. **detect_liquidation_levels** - Find support/resistance
4. **create_chart_annotation** - Draw on charts
5. **create_liquidation_zone** - Mark liquidation zones
6. **generate_strategy** - Build complete strategy

## 🔄 Strategy Building Flow

1. User sends prompt via API
2. Orchestrator Agent receives request
3. Liquidation Agent analyzes price levels (parallel)
4. Indicator Agent analyzes indicators (parallel)
5. Orchestrator synthesizes findings
6. MCP tools create chart annotations
7. Complete strategy returned (<60s)

## 📊 Example Request

```bash
curl -X POST http://localhost:8000/api/strategy/build \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Build a swing trading strategy for Bitcoin using RSI and liquidation zones",
    "symbol": "BTC/USD",
    "timeframe": "1h",
    "risk_tolerance": "medium"
  }'
```

## 🧪 Testing

```bash
# Health check
curl http://localhost:8000/health

# Get market summary
curl http://localhost:8000/api/market-summary/BTC/USD

# Quick analysis
curl http://localhost:8000/api/strategy/analyze/BTC/USD
```

## 📝 Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CEREBRAS_API_KEY` | Cerebras API key | Required |
| `DATABASE_URL` | PostgreSQL connection | Required |
| `REDIS_URL` | Redis connection | `redis://localhost:6379` |
| `FRONTEND_URL` | Frontend URL for CORS | `http://localhost:3000` |
| `BACKEND_PORT` | Backend server port | `8000` |

## 🚦 Status Codes

- `200` - Success
- `404` - Resource not found
- `500` - Internal server error

## 📚 Documentation

Interactive API docs available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## 🔐 Security Notes

- Update CORS origins in production
- Use environment variables for secrets
- Enable authentication middleware (TODO)
- Implement rate limiting (TODO)

## 🐛 Troubleshooting

**Database connection failed**:
- Check TimescaleDB is running
- Verify connection string in .env

**Redis connection failed**:
- Ensure Redis server is running
- Check REDIS_URL in .env

**MCP tools not working**:
- Verify MCP server is running
- Check Python path for mcp/server.py

**Cerebras API errors**:
- Validate CEREBRAS_API_KEY
- Check API rate limits
