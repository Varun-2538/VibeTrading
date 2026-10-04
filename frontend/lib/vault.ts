/**
 * The client side of a trading vault.
 *
 * Deploying, funding, revoking and withdrawing are the owner's transactions, sent
 * from their own wallet — we never hold a key that could do any of them. What we
 * hold is an operator grant the owner makes in `setOperator`, and it can only open
 * and close positions inside their vault.
 *
 * The disclosure hash is load-bearing rather than decorative: the text below is
 * what `keccak256` is taken over, and the vault stores that hash forever, so which
 * wording someone accepted is a fact on-chain rather than a row in our database.
 * Editing the text means minting a new version — never editing an old one.
 */
import { keccak256, parseAbi, stringToHex, type Address } from "viem"

/** Deployed per environment; absent until the factory is deployed on a chain. */
export const VAULT_FACTORY = (process.env.NEXT_PUBLIC_VAULT_FACTORY ?? "") as Address | ""

export const USDC_DECIMALS = 6

/**
 * The exact text a vault's owner accepts. Versioned, and append-only: an old
 * version has to keep resolving to the hash stored in vaults that accepted it.
 */
export const DISCLOSURES: Record<string, string> = {
  v1: [
    "VibeTrading operator grant, version 1.",
    "I am funding a vault contract that I own and control.",
    "VibeTrading may open and close positions inside it, within the caps I set, and cannot withdraw from it.",
    "I can revoke that permission and withdraw at any time, without VibeTrading's cooperation.",
    "Stops and targets are enforced on-chain against a Chainlink price and are not guaranteed fill prices.",
    "Trading can lose money, up to everything in this vault.",
  ].join("\n"),
}

export const CURRENT_DISCLOSURE = "v1"

export function disclosureText(version: string = CURRENT_DISCLOSURE): string {
  const text = DISCLOSURES[version]
  if (!text) throw new Error(`No disclosure text for version ${version}`)
  return text
}

/** What the vault stores, and what the factory is handed at deploy time. */
export function disclosureHash(version: string = CURRENT_DISCLOSURE): `0x${string}` {
  return keccak256(stringToHex(disclosureText(version)))
}

export const FACTORY_ABI = parseAbi([
  "function TVL_CAP() view returns (uint256)",
  "function stable() view returns (address)",
  "function router() view returns (address)",
  "function vaultOf(address owner, address asset) view returns (address)",
  "function deploy(address asset, bytes32 disclosure) returns (address)",
  "event VaultDeployed(address indexed owner, address indexed asset, address vault, bytes32 disclosure)",
])

export const VAULT_ABI = parseAbi([
  "function owner() view returns (address)",
  "function operator() view returns (address)",
  "function operatorExpiry() view returns (uint64)",
  "function stable() view returns (address)",
  "function asset() view returns (address)",
  "function tvlCap() view returns (uint256)",
  "function disclosure() view returns (bytes32)",
  "function maxNotional() view returns (uint256)",
  "function maxTradesPerDay() view returns (uint16)",
  "function maxSlippageBps() view returns (uint16)",
  "function bounty() view returns (uint256)",
  "function tradesToday() view returns (uint16)",
  "function position() view returns (bool open, uint256 spent, uint256 qty, uint256 entryPrice, uint256 stopPrice, uint256 targetPrice, uint64 openedAt, uint64 deadline)",
  "function openFloor(uint256 amountIn) view returns (uint256)",
  "function closeFloor() view returns (uint256)",
  "function stopTriggered() view returns (bool)",
  "function targetTriggered() view returns (bool)",
  "function expired() view returns (bool)",
  "function deposit(uint256 amount)",
  "function withdraw(address token, uint256 amount, address to)",
  "function setOperator(address who, uint64 expiry)",
  "function revokeOperator()",
  "function setCaps(uint256 maxNotional, uint16 maxTradesPerDay, uint16 maxSlippageBps, uint256 bounty)",
  "function closeByOwner() returns (uint256)",
])

export const ERC20_ABI = parseAbi([
  "function balanceOf(address account) view returns (uint256)",
  "function allowance(address owner, address spender) view returns (uint256)",
  "function approve(address spender, uint256 amount) returns (bool)",
])

/** Markets a vault can be deployed for, mirroring VaultFactory's fixed list. */
export const VAULT_MARKETS: { market: string; label: string; asset: Address }[] = [
  { market: "WETH/USDC", label: "ETH", asset: "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1" },
  { market: "WBTC/USDC", label: "BTC", asset: "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f" },
]

export function assetForMarket(market: string): Address | null {
  return VAULT_MARKETS.find((m) => m.market === market)?.asset ?? null
}

/** USDC has six decimals, and a wallet balance is a bigint. */
export function formatUsdc(value: bigint | null | undefined): string {
  if (value === null || value === undefined) return "—"
  const whole = value / 1_000_000n
  const cents = (value % 1_000_000n) / 10_000n
  return `$${whole.toLocaleString()}.${cents.toString().padStart(2, "0")}`
}

export function parseUsdc(input: string): bigint | null {
  const cleaned = input.trim().replace(/[$,]/g, "")
  if (!/^\d+(\.\d{0,6})?$/.test(cleaned)) return null
  const [whole, fraction = ""] = cleaned.split(".")
  return BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, "0"))
}

/** Chainlink prices are 8 decimals; a stop is stored in those units. */
export function formatFeedPrice(value: bigint | null | undefined): string {
  if (value === null || value === undefined || value === 0n) return "—"
  const whole = value / 100_000_000n
  const cents = (value % 100_000_000n) / 1_000_000n
  return `$${whole.toLocaleString()}.${cents.toString().padStart(2, "0")}`
}

export function toFeedPrice(usd: number): bigint {
  return BigInt(Math.round(usd * 1e8))
}

export interface VaultPosition {
  open: boolean
  spent: bigint
  qty: bigint
  entryPrice: bigint
  stopPrice: bigint
  targetPrice: bigint
  openedAt: bigint
  deadline: bigint
}

export interface VaultState {
  address: Address
  balance: bigint
  tvlCap: bigint
  operator: Address
  operatorExpiry: bigint
  maxNotional: bigint
  tradesToday: number
  maxTradesPerDay: number
  position: VaultPosition
}

/**
 * Whether the grant we hold is currently usable, which is not the same question as
 * whether an operator address is set: an expired grant reads as an address and
 * refuses every call.
 */
export function grantActive(state: Pick<VaultState, "operator" | "operatorExpiry">, now: Date = new Date()): boolean {
  const set = state.operator !== "0x0000000000000000000000000000000000000000"
  return set && state.operatorExpiry > BigInt(Math.floor(now.getTime() / 1000))
}

export function grantExpiry(days: number, now: Date = new Date()): bigint {
  return BigInt(Math.floor(now.getTime() / 1000) + days * 24 * 60 * 60)
}

/** Room left under the vault's hard cap, which no one can raise. */
export function headroom(state: Pick<VaultState, "balance" | "tvlCap">): bigint {
  return state.tvlCap > state.balance ? state.tvlCap - state.balance : 0n
}
