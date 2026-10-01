import type { Metadata } from "next"
import { CONTACT_EMAIL } from "@/lib/contact"

export const metadata: Metadata = {
  title: "Risk disclosure — VibeTrading",
  description:
    "VibeTrading performs technical analysis on public market data. It is not investment advice, it executes no trades, and it never touches your exchange account.",
}

export default function RiskPage() {
  return (
    <>
      <h1>Risk disclosure</h1>
      <p className="lede">
        VibeTrading is an analysis tool. It is not a broker, not an adviser, and
        not a signal service. Read this page before you act on anything the app
        shows you.
      </p>

      <h2>This is not financial advice</h2>
      <p>
        Nothing produced by VibeTrading — the levels, the W and M patterns, the
        confidence percentages, the measured-move targets, or anything the chat
        assistant writes — is investment advice, a recommendation, or a
        solicitation to buy or sell anything. It is arithmetic applied to public
        price history, presented for you to interpret. No one at VibeTrading
        knows your finances, your risk tolerance, or your goals, and the app
        does not take them into account.
      </p>
      <p>
        If you want advice, speak to someone licensed to give it in your
        jurisdiction.
      </p>

      <h2>What the app actually does</h2>
      <p>
        It reads recent candles from a public market-data API, then computes
        things you could compute yourself with a spreadsheet and enough
        patience: which prices the market has revisited, and where two lows or
        two highs sit close enough together to form a double bottom or double
        top. Every threshold is a fixed rule expressed in ATR. There is no
        prediction model, no proprietary edge, and no crystal ball.
      </p>
      <p>
        A confidence percentage measures <em>how cleanly a shape matches its
        geometric definition</em> — how close the two lows are, how deep the
        pattern is, how symmetric the legs are. It is not a probability that a
        trade will work. A 90% double bottom is a tidy-looking double bottom,
        nothing more.
      </p>

      <h2>Chart patterns are not predictions</h2>
      <p>
        We have measured this and would rather tell you than let you assume
        otherwise: run the detector over a random walk with no structure in it
        at all, and it finds roughly as many patterns as it finds on real
        Bitcoin data. That is a property of chart patterns in general, not a
        defect in this implementation — random data genuinely contains
        W-shapes. It means a mark on your chart is evidence that a shape is
        present, not evidence that a move will follow.
      </p>

      <h2>Trading can lose you money</h2>
      <p>
        Trading cryptocurrency carries substantial risk, including the total
        loss of the money you put in. Crypto markets run continuously, move
        violently, and are lightly regulated compared with equities. Leverage
        multiplies losses as readily as gains. Past price behaviour does not
        predict future price behaviour. Only risk money you can afford to lose
        entirely.
      </p>

      <h2>What we never do</h2>
      <ul>
        <li>
          <strong>We do not execute trades.</strong> The app has no order
          placement of any kind.
        </li>
        <li>
          <strong>We never ask for exchange API keys.</strong> There is nowhere
          to enter them, and no feature that would use them. If anything ever
          asks you for keys in our name, it is not us.
        </li>
        <li>
          <strong>We do not hold funds or custody assets.</strong> There is no
          wallet, no deposit, and no withdrawal.
        </li>
        <li>
          <strong>We do not manage money</strong> or accept discretionary
          authority over anyone's account.
        </li>
        <li>
          <strong>We do not sell signals, promise returns, or publish track
          records.</strong> Any claim of guaranteed profit attributed to
          VibeTrading is fraudulent.
        </li>
      </ul>

      <h2>The data may be wrong or late</h2>
      <p>
        Market data comes from a third-party public API and is provided as-is.
        It may be delayed, incomplete, or unavailable. Prices shown may differ
        from those on your exchange. Do not rely on this app as your source of
        truth for a live position.
      </p>

      <h2>The software is young</h2>
      <p>
        VibeTrading is in active development and is offered free. It has bugs.
        Several detection rules on this site were corrected in the past week
        after users reported patterns being missed. Treat its output with the
        scepticism you would apply to any early tool.
      </p>

      <h2>Talk to us</h2>
      <p>
        If something the app shows looks wrong, tell us at{" "}
        <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>. Reports like
        that are how the detector gets better.
      </p>
    </>
  )
}
