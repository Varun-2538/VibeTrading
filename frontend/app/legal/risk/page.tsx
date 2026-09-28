import type { Metadata } from "next"
import { CONTACT_EMAIL } from "@/lib/contact"

export const metadata: Metadata = {
  title: "Risk disclosure — VibeTrading",
  description:
    "VibeTrading performs technical analysis on public market data and can alert you when conditions you set are met. It can also trade those conditions inside a contract you own, if you switch that on. It is not investment advice, it never holds your funds, and it never touches your exchange account.",
}

export default function RiskPage() {
  return (
    <>
      <h1>Risk disclosure</h1>
      <p className="lede">
        VibeTrading is an analysis tool. It can watch for conditions you define
        and tell you when they occur, and &mdash; if you set that up &mdash; it
        can trade them inside a contract you own and control. It is not a broker,
        not an adviser, and it chooses nothing for you: the strategy, the size
        and the limits are yours. Read this page before you act on anything the
        app shows you, and read the section on execution twice before you turn it
        on.
      </p>

      <h2>This is not financial advice</h2>
      <p>
        Nothing produced by VibeTrading — the levels, the W and M patterns, the
        head-and-shoulders and cup-and-handle shapes, the candle shapes, the
        confidence percentages, the measured-move targets, the alerts your
        rules fire, or anything the chat assistant writes — is investment
        advice, a recommendation, or a solicitation to buy or sell anything. It is arithmetic applied to public
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

      <h2>Strategy alerts are notifications, not instructions</h2>
      <p>
        You can arm a rule — a pattern shape, or price meeting a support or
        resistance level — and the app will tell you when that condition is met.
        An alert means exactly one thing: the arithmetic described above matched
        on a candle that has closed. It is not a view on whether to trade, it
        carries no opinion about your position or your risk, and it is not a
        signal to act.
      </p>
      <p>
        Alerts are deliberately late. A rule only fires on closed candles, and
        by default only once a pattern is confirmed and has survived a further
        candle — so by the time you hear from us, some of the move has already
        happened. That is the trade we chose: fewer alerts for setups that
        vanish, at the cost of a worse entry.
      </p>
      <p>
        <strong>Do not use alerts as risk management.</strong> They are not a
        stop-loss and not a substitute for one. Delivery is best effort and is
        not guaranteed: our server may be down or restarting, market data may be
        cached or stale, an hourly rule may not notice for several minutes, and
        a rule may simply never fire. If you would be harmed by an alert
        arriving late or not at all, do not depend on it — put a real order on
        your exchange instead.
      </p>
      <p>
        Rules are private to the wallet address that created them. Connecting a
        wallet and signing a message is how we establish that address, and for
        alerts that is all it does: no transaction, no token approval, and no
        ability for us to move anything you hold. Execution is a separate,
        explicit step — a contract you deploy and a permission you grant in
        their own transactions, which you can revoke at any time. Signing in has
        never authorised spending and still does not. If you lose access to that
        address, you lose access to the rules under it, and to any vault you
        deployed from it.
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

      <h2>Backtests are not forecasts</h2>
      <p>
        A backtest replays stored candles through the same code that fires your
        alerts, and models entries, exits, fees and slippage. It cannot model
        the order book you would really have traded into, funding, exchange
        outages, or your own behaviour on the day.
      </p>
      <p>
        Costs are charged the way a decentralised exchange charges them: the
        pool&apos;s fee tier on every swap, so twice per trade, plus price impact
        on every fill and gas per swap. Gas is a cost in dollars, so the position
        size you enter decides what share of the trade it is; a small position
        pays a large share. Every report shows what the strategy earned before
        costs, what costs took, and what was left — and those three numbers, not
        the last one alone, are what tell you whether a losing result is a weak
        signal or an expensive round trip. The tiers, the impact and the gas are
        yours to set: we cannot know which pool you route through.
      </p>
      <p>
        Results on the <em>seen</em> period are selected: the platform searches
        many settings there and keeps the best, which flatters that number by
        construction. The <em>unseen</em> period is measured once, with that
        single choice, and it is the number worth reading. A large drop from
        seen to unseen is ordinary, and we flag it — it means the settings fitted
        noise rather than anything that repeats. Every report says how many
        settings were tried. Fewer than thirty trades tells you very little
        either way, and we say so on the report rather than leaving you to
        notice.
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
          <strong>We do not hold your funds.</strong> There is no deposit to us
          and no balance with us. If you use execution, your money sits in a
          contract you deployed and own, and the permission you give us cannot
          withdraw from it — there is no function in that contract by which we
          could, whatever we wanted or were asked to do.
        </li>
        <li>
          <strong>We never ask for exchange API keys, seed phrases or private
          keys.</strong> There is nowhere to enter them and no feature that would
          use them. If anything ever asks you for them in our name, it is not us.
        </li>
        <li>
          <strong>We cannot move a stop once it is set.</strong> Your stop, your
          target and your deadline are written into the contract when a position
          opens, and nothing changes them afterwards — not us, and not you.
        </li>
        <li>
          <strong>We do not choose what to trade.</strong> Every rule, every
          limit and every size is yours. We do not recommend strategies and we do
          not accept discretion to invent one.
        </li>
        <li>
          <strong>We do not sell signals, promise returns, or publish track
          records.</strong> Any claim of guaranteed profit attributed to
          VibeTrading is fraudulent.
        </li>
      </ul>

      <h2>If you switch execution on</h2>
      <p>
        Execution is off. It is off for everyone, on our side as well as yours,
        and turning it on takes three separate things: a contract you deploy
        yourself, a permission you grant on-chain, and a backtest that passes.
        Arming a rule for alerts does none of them. What follows describes what
        happens once you have done all three.
      </p>
      <p>
        <strong>Your money stays in your contract.</strong> You deploy a vault,
        you fund it, you own it. We hold a permission that can do exactly two
        things inside it: open a position and close one. It cannot transfer, it
        cannot approve anyone else, it cannot change where a trade routes, and it
        expires by itself. You can revoke it in one transaction, without our
        cooperation and without telling us.
      </p>
      <p>
        <strong>Your stop does not depend on us.</strong> It is stored in the
        contract and checked against a Chainlink price. Anyone at all can send the
        transaction that closes a stopped position, and the contract pays them a
        small fee from the vault for doing it — so if our servers are down, a
        stranger has a reason to close your position for you. That is deliberate,
        and it is why a stop here is not best-effort in the way an alert is.
      </p>
      <p>
        <strong>A stop is not a fill price.</strong> A stop at $100 means the
        contract will allow an exit once the price is at or below $100. It does
        not mean you get $100. If the market gaps you get whatever the pool pays
        when the transaction lands, which can be much worse. Our backtests model
        the same thing, so a report and a real trade speak the same language —
        but neither is a promise.
      </p>
      <p>
        <strong>Three different prices are involved, and they disagree.</strong>{" "}
        Your rule fires on candles from a centralised exchange. Your stop is
        authorised by a Chainlink feed. Your trade fills at whatever a Uniswap
        pool quotes at that moment. We record the gap on every fill, in basis
        points, and show it to you — because it is real, and you should see it
        rather than discover it.
      </p>
      <p>
        <strong>Costs can exceed the edge.</strong> A swap pays the pool's fee
        going in and coming out, plus gas. Measured against a 1.5-ATR stop, that
        is roughly 0.03R a trade on a daily chart and more than 2R on a
        five-minute one. That is why the app refuses to arm a strategy whose own
        backtest does not clear its costs, and why intraday trading on a
        decentralised exchange is arithmetic rather than opinion.
      </p>
      <p>
        <strong>A backtest is required, and it is still not a forecast.</strong>{" "}
        A rule cannot be armed for execution unless a backtest of that exact rule,
        on data the tuning never saw, clears a bar you set yourself. That check
        exists to stop the obvious mistakes. It cannot tell you the future, and a
        strategy that passed it can lose money immediately and continuously.
      </p>
      <p>
        <strong>Start in shadow mode.</strong> Shadow records every trade the rule
        would have made and sends none of them. A week of it costs nothing and
        tells you what your strategy really pays in fees, gas and slippage against
        what the backtest assumed. Skipping it is the most expensive mistake
        available here.
      </p>
      <p>
        <strong>The contract is new and unaudited.</strong> It carries a hard cap
        of a few hundred dollars per vault, written into the code so that we
        cannot raise it either, and it will not hold more until someone who is not
        us has audited it. Smart contracts lose money to bugs. This one could.
      </p>
      <p>
        <strong>Software fails, and this software is young.</strong> Our executor
        can be down, slow or wrong. It can miss an entry entirely — which costs
        you an opportunity rather than capital, because entries depend on us and
        exits do not. Read that sentence again before you rely on either.
      </p>

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
