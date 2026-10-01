import type { Metadata } from "next"
import { CONTACT_EMAIL } from "@/lib/contact"

export const metadata: Metadata = {
  title: "Privacy — VibeTrading",
  description:
    "VibeTrading has no accounts and no logins. What it collects, what it sends to third parties, and what it keeps.",
}

export default function PrivacyPage() {
  return (
    <>
      <h1>Privacy</h1>
      <p className="lede">
        VibeTrading has no accounts, no logins and no passwords. We hold almost
        nothing about you, and this page says exactly what "almost" means.
      </p>
      <p className="meta">Last updated 12 August 2026.</p>

      <h2>What we do not collect</h2>
      <p>
        There is no sign-up, so there is no name, email address, password or
        profile. We do not ask for identity documents, phone numbers, payment
        details or exchange credentials, because the app has no feature that
        uses any of them. We do not set advertising cookies and we do not run
        third-party ad trackers.
      </p>

      <h2>What is collected</h2>
      <h3>Aggregate traffic statistics</h3>
      <p>
        The site uses Vercel Analytics to count page views and see which pages
        get used. It is configured without cookies and does not build a profile
        or follow you across other sites. We see totals, not people.
      </p>
      <h3>Chat messages</h3>
      <p>
        When you type a question to the assistant, that text is sent to our
        server and on to Cerebras, which runs the language model that answers
        it. Please do not put anything sensitive or personally identifying into
        the chat box — there is no reason the app needs it, and treating it as a
        private channel would be a mistake.
      </p>
      <h3>Ordinary server logs</h3>
      <p>
        Our server and the platforms in front of it keep the usual technical
        logs — IP address, timestamp, requested URL, user agent — for
        reliability and abuse prevention. This is standard for any website and
        we do not use those logs to identify individuals.
      </p>

      <h2>What we store</h2>
      <p>
        Our database holds market data, not user data: candles fetched from the
        public market API, and chart annotations recorded against a trading
        symbol. None of it is attached to a person, because we have no concept
        of a person — there are no accounts to attach it to.
      </p>

      <h2>Who else is involved</h2>
      <ul>
        <li>
          <strong>Binance public market data API</strong> — where price candles
          come from. Requests are made by our server, not your browser, so your
          browser is not talking to them directly.
        </li>
        <li>
          <strong>Cerebras</strong> — runs the language model behind the chat
          assistant. Receives the text of your chat messages.
        </li>
        <li>
          <strong>Vercel</strong> — hosts the website and provides the
          cookieless analytics described above.
        </li>
        <li>
          <strong>Google Cloud Platform</strong> — hosts the backend server and
          database, on Compute Engine in the asia-south1 region.
        </li>
      </ul>
      <p>
        Each of these processes data under its own privacy terms. We do not sell
        data to anyone, and we do not share it beyond what is needed to make the
        app work.
      </p>

      <h2>How long things are kept</h2>
      <p>
        Market data and annotations are kept for as long as they are useful for
        analysis. Server logs are kept for a short operational period and then
        rotate away. Because we do not link anything to an identity, there is no
        personal profile accumulating over time.
      </p>

      <h2>Your rights</h2>
      <p>
        Depending on where you live you may have rights to access, correct or
        delete personal data held about you. In our case the honest answer is
        usually that we hold none, since there is no account to look up. If you
        believe we hold something about you and want it removed, write to{" "}
        <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a> and we will deal
        with it.
      </p>

      <h2>Children</h2>
      <p>
        This site is not intended for anyone under 18 and we do not knowingly
        collect information from children.
      </p>

      <h2>Changes</h2>
      <p>
        If this policy changes we will update the date at the top. The project
        is small enough that we will not pretend to run a formal notification
        process.
      </p>

      <h2>Contact</h2>
      <p>
        VibeTrading is an independent project, not an incorporated company.
        Privacy questions go to{" "}
        <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
      </p>
    </>
  )
}
