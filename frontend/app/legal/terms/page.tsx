import type { Metadata } from "next"
import { CONTACT_EMAIL } from "@/lib/contact"

export const metadata: Metadata = {
  title: "Terms of use — VibeTrading",
  description:
    "The terms you accept by using VibeTrading: informational use only, no warranty, and no liability for trading losses.",
}

export default function TermsPage() {
  return (
    <>
      <h1>Terms of use</h1>
      <p className="lede">
        Plain terms for a free tool that analyses markets and, if you tell it to,
        trades them for you. By using VibeTrading you accept
        them.
      </p>
      <p className="meta">Last updated 12 August 2026.</p>

      <h2>Who runs this</h2>
      <p>
        VibeTrading is an independent software project, operated by its
        developer and reachable at{" "}
        <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>. It is not an
        incorporated company, not a registered broker or investment adviser, and
        not regulated by any financial authority. We are not claiming
        credentials we do not have.
      </p>

      <h2>What the service is</h2>
      <p>
        A free tool that computes technical analysis over public market data and
        draws it on a chart, watches for conditions you define, and — if you
        set that up yourself — sends the trades those conditions call for into
        a contract you own. It is provided for research and education. See the{" "}
        <a href="/legal/risk">risk disclosure</a> for what that does and does not
        mean — those statements are part of these terms.
      </p>

      <h2>If you use execution</h2>
      <p>
        Execution is off unless you switch it on, and switching it on takes three
        things you do yourself: deploying a vault contract, granting it permission
        to trade on your behalf, and passing a backtest of the rule you want
        traded. We are not a broker, a dealer, an exchange or a portfolio manager,
        and none of those things changes because a rule you wrote fires and a
        contract you own acts on it.
      </p>
      <p>
        Your funds stay in your contract. We never hold them, and the permission
        you grant cannot withdraw from it — it can only open and close
        positions, within caps you set, and it expires. You can revoke it in one
        transaction without our cooperation, and you should if anything here
        worries you.
      </p>
      <p>
        You are responsible for the strategy, the sizing and the limits, for
        checking that they are what you meant, and for the money at stake. The
        trades are yours. We supply the software that sends them, and we make no
        representation that any strategy — including one that passed its
        backtest — will be profitable.
      </p>

      <h2>Your responsibility</h2>
      <p>
        Every trading decision you make is yours alone. You are responsible for
        your own research, your own risk management, and for complying with the
        laws and financial regulations that apply where you live. If
        cryptocurrency trading is restricted in your jurisdiction, do not use
        this tool to conduct it.
      </p>

      <h2>Acceptable use</h2>
      <p>You agree not to:</p>
      <ul>
        <li>
          scrape, overload, or attempt to disrupt the service, or place
          automated load on it beyond ordinary interactive use;
        </li>
        <li>
          resell the output as a paid signal service, or present it as advice
          from a licensed professional;
        </li>
        <li>
          represent VibeTrading as endorsing a trade, a token, or a return, or
          use its name to solicit money from anyone;
        </li>
        <li>
          attempt to gain unauthorised access to the servers, database or
          infrastructure behind it;
        </li>
        <li>use it for anything unlawful.</li>
      </ul>

      <h2>No warranty</h2>
      <p>
        The service is provided "as is" and "as available", without warranties
        of any kind, express or implied, including fitness for a particular
        purpose. We do not warrant that it will be accurate, uninterrupted,
        error-free, or that the market data behind it is correct or timely. It
        is early software and it has bugs.
      </p>

      <h2>Limitation of liability</h2>
      <p>
        To the fullest extent permitted by law, we are not liable for any
        trading losses, lost profits, missed opportunities, or any indirect or
        consequential damages arising from your use of the service, whether the
        output was accurate or not. You use it at your own risk. Nothing here
        limits liability that cannot lawfully be limited.
      </p>

      <h2>Availability</h2>
      <p>
        This is a free service with no uptime guarantee. It may be slow,
        unavailable, changed, or discontinued at any time without notice, and
        features may be removed as the project evolves.
      </p>

      <h2>Intellectual property</h2>
      <p>
        The VibeTrading name and interface belong to the project. Market data
        belongs to its original providers and is used through their public
        interfaces. You keep whatever you write in the chat.
      </p>

      <h2>Changes to these terms</h2>
      <p>
        These terms may change as the project develops; the date at the top will
        be updated when they do. Continuing to use the service after a change
        means you accept the revised terms.
      </p>

      <h2>Contact</h2>
      <p>
        Anything at all — a bug, a legal question, a takedown request —{" "}
        <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
      </p>
    </>
  )
}
