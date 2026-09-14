"""
Test AI Agents (Cerebras LLMs) to detect liquidation levels
Uses: Orchestrator Agent → Liquidation Agent → MCP Tools
"""
import asyncio
from models.database import db
from agents.orchestrator import OrchestratorAgent
from agents.liquidation_agent import LiquidationAgent
from mcp_server.client import mcp_client
import json


async def test_liquidation_agent(symbol: str):
    """Test Liquidation Agent on a single stock"""
    print(f"\n{'='*80}")
    print(f"[AI AGENT] Analyzing {symbol} for Liquidation Levels")
    print(f"{'='*80}\n")

    # Initialize Liquidation Agent
    liquidation_agent = LiquidationAgent()

    # Run analysis
    print(f"[AGENT] Cerebras Llama 3.1 8B analyzing {symbol}...")
    analysis = await liquidation_agent.analyze(
        symbol=symbol,
        timeframe="1h",
        lookback_periods=100
    )

    # Display results
    print(f"\n[ANALYSIS COMPLETE] {symbol}")
    print(f"Timestamp: {analysis.get('timestamp')}")
    current_price = analysis.get('current_price')
    if current_price:
        print(f"Current Price: Rs.{current_price:.2f}\n")
    else:
        print(f"Current Price: Not available\n")

    print(f"[SUPPORT LEVELS] ({len(analysis.get('support_levels', []))} found):")
    for i, level in enumerate(analysis.get('support_levels', [])[:5], 1):
        print(f"  {i}. Rs.{level['price']:.2f} - {level['strength'].upper()}")
        print(f"     Reasoning: {level['reasoning']}")

    print(f"\n[RESISTANCE LEVELS] ({len(analysis.get('resistance_levels', []))} found):")
    for i, level in enumerate(analysis.get('resistance_levels', [])[:5], 1):
        print(f"  {i}. Rs.{level['price']:.2f} - {level['strength'].upper()}")
        print(f"     Reasoning: {level['reasoning']}")

    print(f"\n[LIQUIDATION ZONES] ({len(analysis.get('liquidation_zones', []))} found):")
    for i, zone in enumerate(analysis.get('liquidation_zones', [])[:3], 1):
        print(f"  {i}. Rs.{zone['start_price']:.2f} - Rs.{zone['end_price']:.2f}")
        print(f"     Label: {zone['label']}")
        print(f"     Strength: {zone['strength'].upper()}")

    print(f"\n[AI SUMMARY]:")
    print(f"{analysis.get('analysis_summary', 'No summary available')}")

    return analysis


async def test_orchestrator(symbol: str, user_prompt: str):
    """Test full Orchestrator Agent (coordinates multiple agents)"""
    print(f"\n{'='*80}")
    print(f"[ORCHESTRATOR] Building Trading Strategy for {symbol}")
    print(f"{'='*80}\n")

    # Initialize Orchestrator
    orchestrator = OrchestratorAgent()

    # Build strategy
    print(f"[AGENT] Cerebras Llama 3.1 70B orchestrating analysis...")
    print(f"[USER PROMPT] {user_prompt}\n")

    strategy = await orchestrator.build_strategy(
        symbol=symbol,
        timeframe="1h",
        user_prompt=user_prompt
    )

    # Display strategy
    print(f"\n[STRATEGY COMPLETE] {symbol}")
    print(f"\nStrategy Type: {strategy.get('strategy_type', 'N/A')}")
    print(f"Market Bias: {strategy.get('market_bias', 'N/A')}")
    print(f"Confidence: {strategy.get('confidence', 0):.1f}%\n")

    print(f"[ENTRY CONDITIONS]:")
    for condition in strategy.get('entry_conditions', []):
        print(f"  - {condition}")

    print(f"\n[EXIT CONDITIONS]:")
    for condition in strategy.get('exit_conditions', []):
        print(f"  - {condition}")

    print(f"\n[RISK MANAGEMENT]:")
    risk = strategy.get('risk_management', {})
    print(f"  Stop Loss: Rs.{risk.get('stop_loss', 0):.2f}")
    print(f"  Take Profit: Rs.{risk.get('take_profit', 0):.2f}")
    print(f"  Risk/Reward: {risk.get('risk_reward_ratio', 0):.2f}")

    print(f"\n[KEY LEVELS]:")
    for level in strategy.get('key_levels', []):
        print(f"  - {level}")

    print(f"\n[AI REASONING]:")
    print(f"{strategy.get('reasoning', 'No reasoning available')}")

    return strategy


async def main():
    """Main test function"""
    await db.connect()

    print("\n" + "="*80)
    print("AI AGENT TESTING - CEREBRAS LLAMA 3.1 MODELS")
    print("="*80)

    try:
        await mcp_client.connect()
        print("[OK] MCP Client connected")
    except Exception as e:
        print(f"[WARNING] MCP Client connection failed: {e}")
        print("[INFO] Continuing without MCP (will use direct repository calls)")

    try:
        # Test 1: Liquidation Agent on RELIANCE
        print("\n[TEST 1] Liquidation Agent - RELIANCE")
        reliance_analysis = await test_liquidation_agent("RELIANCE")

        # Test 2: Liquidation Agent on TCS
        print("\n[TEST 2] Liquidation Agent - TCS")
        tcs_analysis = await test_liquidation_agent("TCS")

        # Test 3: Full Orchestrator on INFY
        print("\n[TEST 3] Orchestrator Agent - INFY")
        user_prompt = "I want a swing trading strategy for INFY. Find good entry points near support levels with stop loss below key support."
        infy_strategy = await test_orchestrator("INFY", user_prompt)

        # Save results
        results = {
            "reliance_liquidation": reliance_analysis,
            "tcs_liquidation": tcs_analysis,
            "infy_strategy": infy_strategy
        }

        # Convert datetime objects to strings for JSON serialization
        def convert_to_json(obj):
            if hasattr(obj, 'isoformat'):
                return obj.isoformat()
            return str(obj)

        output_file = "ai_agent_analysis.json"
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, default=convert_to_json)

        print(f"\n[SAVED] AI analysis saved to: {output_file}")

    finally:
        try:
            await mcp_client.disconnect()
        except:
            pass
        await db.disconnect()

    print("\n" + "="*80)
    print("[COMPLETE] All AI agent tests finished successfully!")
    print("="*80)


if __name__ == "__main__":
    asyncio.run(main())
