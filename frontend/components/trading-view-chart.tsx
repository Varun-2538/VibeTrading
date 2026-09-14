"use client"

import { useEffect, useRef, useState } from "react"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"

interface LiquidityLevel {
  price: number
  strength: string
}

interface LiquidityData {
  current_price: number
  support_levels: LiquidityLevel[]
  resistance_levels: LiquidityLevel[]
}

interface TradingViewChartProps {
  symbol?: string
  onSymbolChange?: (symbol: string) => void
  liquidityData?: { symbol: string; liquidityData: LiquidityData } | null
}

const CRYPTO_PAIRS = [
  { symbol: "BTCUSDT", name: "Bitcoin", tvSymbol: "BINANCE:BTCUSDT" },
  { symbol: "ETHUSDT", name: "Ethereum", tvSymbol: "BINANCE:ETHUSDT" },
  { symbol: "BNBUSDT", name: "Binance Coin", tvSymbol: "BINANCE:BNBUSDT" },
  { symbol: "SOLUSDT", name: "Solana", tvSymbol: "BINANCE:SOLUSDT" },
  { symbol: "XRPUSDT", name: "Ripple", tvSymbol: "BINANCE:XRPUSDT" },
  { symbol: "ADAUSDT", name: "Cardano", tvSymbol: "BINANCE:ADAUSDT" },
  { symbol: "DOGEUSDT", name: "Dogecoin", tvSymbol: "BINANCE:DOGEUSDT" },
  { symbol: "DOTUSDT", name: "Polkadot", tvSymbol: "BINANCE:DOTUSDT" },
  { symbol: "AVAXUSDT", name: "Avalanche", tvSymbol: "BINANCE:AVAXUSDT" },
]

export default function TradingViewChart({ symbol, onSymbolChange, liquidityData }: TradingViewChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const widgetRef = useRef<any>(null)
  const [selectedStock, setSelectedStock] = useState(symbol || "BTCUSDT")
  const [markedLevels, setMarkedLevels] = useState<any[]>([])

  useEffect(() => {
    // TradingView Widget Script
    const script = document.createElement("script")
    script.src = "https://s3.tradingview.com/tv.js"
    script.async = true
    script.onload = () => {
      if (containerRef.current && typeof window !== "undefined" && (window as any).TradingView) {
        const tvSymbol = CRYPTO_PAIRS.find((s) => s.symbol === selectedStock)?.tvSymbol || "BINANCE:BTCUSDT"

        widgetRef.current = new (window as any).TradingView.widget({
          autosize: true,
          symbol: tvSymbol,
          interval: "60", // 1 hour
          timezone: "Etc/UTC",
          theme: "dark",
          style: "1",
          locale: "en",
          toolbar_bg: "#0a0a0f",
          enable_publishing: false,
          allow_symbol_change: false,
          container_id: "tradingview_chart",
          hide_top_toolbar: false,
          hide_side_toolbar: false,
          save_image: false,
          backgroundColor: "#0a0a0f",
          gridColor: "rgba(255, 255, 255, 0.06)",
        })
      }
    }
    document.head.appendChild(script)

    return () => {
      if (document.head.contains(script)) {
        document.head.removeChild(script)
      }
    }
  }, [selectedStock])

  // Draw liquidity levels when data is provided
  useEffect(() => {
    if (!liquidityData || !widgetRef.current) return

    const { symbol: levelSymbol, liquidityData: data } = liquidityData

    // Only draw if symbol matches
    if (levelSymbol !== selectedStock) return

    // Wait for widget to be ready
    widgetRef.current.onChartReady(() => {
      const chart = widgetRef.current.chart()

      // Remove previous levels
      markedLevels.forEach((shape) => {
        try {
          chart.removeEntity(shape)
        } catch (e) {
          // Ignore if entity doesn't exist
        }
      })

      const newShapes: any[] = []

      // Draw support levels (green)
      data.support_levels?.forEach((level, index) => {
        const shape = chart.createShape(
          { time: chart.getVisibleRange().from, price: level.price },
          {
            shape: "horizontal_line",
            lock: false,
            disableSelection: false,
            disableSave: false,
            disableUndo: false,
            overrides: {
              linecolor: level.strength === "strong" ? "#00ff00" : level.strength === "medium" ? "#90EE90" : "#C8E6C9",
              linewidth: level.strength === "strong" ? 2 : 1,
              linestyle: level.strength === "weak" ? 2 : 0, // 2 = dashed
              showLabel: true,
              textcolor: "#00ff00",
              fontsize: 12,
              text: `Support ${level.price.toFixed(2)} (${level.strength})`,
            },
          }
        )
        newShapes.push(shape)
      })

      // Draw resistance levels (red)
      data.resistance_levels?.forEach((level, index) => {
        const shape = chart.createShape(
          { time: chart.getVisibleRange().from, price: level.price },
          {
            shape: "horizontal_line",
            lock: false,
            disableSelection: false,
            disableSave: false,
            disableUndo: false,
            overrides: {
              linecolor: level.strength === "strong" ? "#ff0000" : level.strength === "medium" ? "#FF6B6B" : "#FFCDD2",
              linewidth: level.strength === "strong" ? 2 : 1,
              linestyle: level.strength === "weak" ? 2 : 0, // 2 = dashed
              showLabel: true,
              textcolor: "#ff0000",
              fontsize: 12,
              text: `Resistance ${level.price.toFixed(2)} (${level.strength})`,
            },
          }
        )
        newShapes.push(shape)
      })

      setMarkedLevels(newShapes)
    })
  }, [liquidityData])

  // Update when symbol prop changes (from chat)
  useEffect(() => {
    if (symbol && symbol !== selectedStock) {
      setSelectedStock(symbol)
    }
  }, [symbol])

  const handleSymbolChange = (newSymbol: string) => {
    setSelectedStock(newSymbol)
    if (onSymbolChange) {
      onSymbolChange(newSymbol)
    }
  }

  const currentCrypto = CRYPTO_PAIRS.find((s) => s.symbol === selectedStock)

  return (
    <div className="h-full w-full bg-card flex flex-col">
      {/* Crypto Selector Header */}
      <div className="border-b border-border px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Select value={selectedStock} onValueChange={handleSymbolChange}>
            <SelectTrigger className="w-[280px] bg-secondary border-border">
              <SelectValue placeholder="Select cryptocurrency" />
            </SelectTrigger>
            <SelectContent>
              {CRYPTO_PAIRS.map((crypto) => (
                <SelectItem key={crypto.symbol} value={crypto.symbol}>
                  <div className="flex items-center justify-between w-full">
                    <span className="font-semibold">{crypto.symbol}</span>
                    <span className="text-xs text-muted-foreground ml-2">{crypto.name}</span>
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Badge variant="outline" className="text-xs bg-orange-500/10 text-orange-500 border-orange-500/20">
            Crypto
          </Badge>
        </div>
        {currentCrypto && <div className="text-sm text-muted-foreground">{currentCrypto.name}</div>}
      </div>

      {/* TradingView Chart */}
      <div className="flex-1 relative">
        <div id="tradingview_chart" ref={containerRef} className="absolute inset-0" />
      </div>
    </div>
  )
}
