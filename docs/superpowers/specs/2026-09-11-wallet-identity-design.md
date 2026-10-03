# Wallet identity for strategy rules

**Date:** 11 September 2026
**Status:** approved, implementing

## Problem

Two defects, one cause.

1. **Fired signals leak to every visitor.** `broadcast_strategy_signal` in
   `controllers/websocket_controller.py` calls `broadcast_to_symbol`, which sends to every
   socket subscribed to that symbol. A rule fired by one user is delivered to everyone
   watching that pair. The panel filters nothing and renders any `strategy_signal` frame.
2. **Ownership is unverified.** `X-Owner-Key` is a browser-minted UUID. Anyone who sends
   another person's key gets their rules. The REST layer is scoped (`WHERE owner_key = $1`,
   404 on mismatch) so it does not leak by accident, but it authenticates nothing.

Replacing the UUID with a wallet address alone would make (2) *worse*: addresses are public,
so impersonation would become trivial. The address is only meaningful once the server has
verified a signature proving control of it.

## Decisions taken

| Question | Decision |
|---|---|
| Existing anonymous rules | **Hard cutover** — deleted. Single identity model, no dual path. |
| Wallet stack | **wagmi + viem, injected connectors only.** No WalletConnect projectId, no third-party signup. Cost: no mobile deep-linking. |
| Anonymous access | **Wallet required** to build or view rules. |
| Chain | **Arbitrum One (42161)**, enforced in the signed message. |

## 1. Identity: SIWE with a server-built message

Once per session:

1. Connect injected wallet → address + chainId. Wrong chain offers `switchChain`.
2. `GET /api/auth/nonce?address=0x…` → server mints a nonce, stores
   `{address, chain_id, issued_at}` in Redis under a 5-minute TTL, and returns **the complete
   EIP-4361 message to sign**.
3. Wallet signs it verbatim (`personal_sign`).
4. `POST /api/auth/verify {address, nonce, signature}` → server reloads the Redis record,
   **reconstructs the exact message it issued**, recovers the signer via `eth-account`,
   compares against the stored address, deletes the nonce, returns a JWT.
5. All `/api/rules/*` calls carry `Authorization: Bearer <jwt>`.

### Why the server builds the message

The server never parses attacker-controlled SIWE text. Every class of hand-rolled SIWE parser
bug — reordered fields, injected newlines, a nonce that is really part of the statement —
cannot occur, because there is nothing to parse. Verification reduces to one string
comparison and one signature recovery. The message keeps the standard EIP-4361 shape so
wallets render it as a normal sign-in prompt.

### Replay and race safety

- The nonce is deleted on use. Redis `DEL` is atomic, so of two concurrent verifies for the
  same nonce exactly one sees `delete() == True`; the other is rejected. Single-use is
  therefore enforced by Redis, not by a read-then-write check.
- The 5-minute TTL bounds the window for a nonce that is never spent.
- `cache_service` degrades silently when Redis is down (`get` → `None`, `set` → `False`).
  That is fail-closed for sign-in, which is correct, but `/api/auth/nonce` must check the
  `set` return and answer **503** rather than hand back a message that can never verify.

### JWT

HS256, `sub` = lowercased address, 7-day expiry. `jwt_secret: str` is added to
`config/settings.py` with **no default**, matching how `llm_api_key` and `database_url`
already fail fast, so a misconfigured deploy refuses to boot instead of quietly signing
tokens with a guessable key. This is a deploy step: the production `.env` needs the value
before the image ships.

New backend dependencies: `eth-account`, `pyjwt`.

### CORS

`main.py` currently sets `allow_origins=[frontend_url, "http://localhost:3000", "*"]`. The
`"*"` makes the whole API world-readable from any origin, which would let any site drive the
nonce handshake. Narrowed to the explicit origins.

## 2. Closing the broadcast leak

Strategy signals move **off** the market socket onto a new `/ws/rules`:

- First frame must be `{type: "auth", token}`; otherwise the server closes with 1008 after a
  short grace period. The token travels in a message rather than a query string because query
  strings are recorded in access logs, and browsers cannot set headers on a WebSocket.
- `ConnectionManager` gains an owner-keyed registry. `broadcast_strategy_signal` becomes
  owner-targeted, and the `broadcast_to_symbol` path stops carrying `strategy_signal`
  entirely — so the leak closes by construction rather than by a filter someone can forget.
- Price and market frames are unchanged and remain unauthenticated.

Two consequences fall out for free: a rule on one symbol now reaches the user while they are
viewing another (impossible with a per-symbol socket), and one socket serves the whole session
instead of one per symbol.

The dead `/ws/strategy/{symbol}` stub — which accepts its socket without registering with the
manager, so it can never receive a broadcast — is replaced by this endpoint.

## 3. Data and the cutover

`db/migrations/002_wallet_identity.sql`, applied by the existing `bootstrap_schema()`:

```sql
DELETE FROM strategy_rules WHERE owner_kind = 'anon';   -- events cascade
ALTER TABLE strategy_rules ALTER COLUMN owner_kind SET DEFAULT 'wallet';
```

Re-running is a no-op once anonymous rules can no longer be created, so this is safe under a
bootstrap that runs on every boot. `owner_key` stays `TEXT`; a lowercased `0x…` address needs
no schema change.

This deletes the existing BTCUSDT rule and its one fired event. An equivalent rule is re-armed
after deploy so production is not left with an empty panel.

`require_owner_key` becomes `require_owner`: it decodes the JWT and returns the lowercased
address, answering **401** on a missing, invalid or expired token (the current code answers
400). The 404-on-mismatch behaviour is unchanged. Addresses are normalised to lowercase
everywhere, so `0xAbC…` and `0xabc…` cannot fragment into two owners.

## 4. Frontend

| File | Purpose |
|---|---|
| `lib/wallet.ts` | wagmi config: `arbitrum` chain, `injected()` only |
| `components/wallet-provider.tsx` | `WagmiProvider` + `QueryClientProvider`, mounted in `app/app/layout.tsx` |
| `lib/session.ts` | runs the handshake, holds the JWT, clears on 401 and re-prompts |
| `hooks/use-session.ts` | state machine: `disconnected → wrong-chain → needs-signature → ready` |
| `components/analysis-panel.tsx` | tabs replaced by a connect card until `ready` |
| `lib/rules.ts` | `Authorization: Bearer` |
| `lib/owner.ts` | **deleted** |
| `hooks/use-strategy-socket.ts` | points at `/ws/rules`, loses its symbol dependency |

The provider is mounted in `app/app/layout.tsx` rather than the root layout so the legal and
marketing pages do not pay the bundle cost.

**Account switching must invalidate the session.** wagmi reports the account change, but the
JWT still names the previous address — left unhandled, the user sits looking at another
account's rules. A mismatch discards the token rather than merely hiding it. This is the
detail such implementations most often miss.

Switching *chain* is treated differently, revising the original plan to clear the session in
both cases. A signature proves control of an address; that proof does not expire because the
wallet moved to another network. So a wrong chain gates the panel and offers a switch, but
keeps the session — otherwise hopping to Ethereum and back would demand a fresh signature for
no security benefit. Note that `address` is briefly `undefined` while wagmi restores a
connection, and that must not be read as a mismatch, or every reload would sign the user out.

## 5. Testing

`backend/tests/test_auth.py`, signing with a fixed key via `eth_account.Account.from_key` so
it is deterministic and offline:

- nonce is single-use — replay returns 401
- a signature from the wrong key is rejected
- tampered and expired JWTs are rejected
- chainId is enforced
- address case does not fragment ownership

Plus a WebSocket test with two fake sockets asserting only the matching owner receives a
signal. That is the regression test for the leak.

The rule engine tests need no change; the engine never sees identity. The frontend has no test
harness and none is being introduced — that path is verified manually against the deployment.

## 6. Legal consequences

Both must change with this feature:

- `app/legal/privacy/page.tsx` says the identifier "is not derived from you or your device".
  A wallet address is the opposite: persistent, pseudonymous, publicly linkable to on-chain
  history, and arguably personal data under GDPR.
- `app/legal/risk/page.tsx` says "There is no wallet, no deposit, and no withdrawal."
  Connecting for identity creates no custody, so the substance holds, but the sentence stops
  being literally true.

## Scope limit

This authenticates *an address*. Signing in is not authorising a trade, and nothing here lets
a rule spend anything. It is the foundation Phase 2 needs, not Phase 2.
