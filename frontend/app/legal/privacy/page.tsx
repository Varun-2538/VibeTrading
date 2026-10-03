import type { Metadata } from "next"
import { CONTACT_EMAIL } from "@/lib/contact"
import { FOUNDERS_SENTENCE } from "@/lib/company"

export const metadata: Metadata = {
  title: "Privacy — VibeTrading",
  description:
    "VibeTrading has no sign-up and no password. What it collects, what a wallet address means for your privacy, what it sends to third parties, and what it keeps.",
}

export default function PrivacyPage() {
  return (
    <>
      <h1>Privacy</h1>
      <p className="lede">
        VibeTrading has no sign-up, no password and no email address. One feature
        — strategy rules — identifies you, and it does so by wallet address. This
        page says exactly what that means and what else we hold.
      </p>
      <p className="meta">Last updated 11 September 2026.</p>

      <h2>What we do not collect</h2>
      <p>
        There is no registration, so there is no name, email address, password or
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
        server and on to Groq, which runs the language model that answers
        it. Please do not put anything sensitive or personally identifying into
        the chat box — there is no reason the app needs it, and treating it as a
        private channel would be a mistake.
      </p>
      <h3>Your wallet address, if you build strategy rules</h3>
      <p>
        Strategy rules are private to whoever created them, so that feature needs
        to know who is asking. Connecting a wallet and signing a message proves
        you control an address, and we store that address alongside your rules.
        We ask your wallet for one signature and nothing else: we request no
        token approvals, we cannot move anything, and signing in authorises no
        transaction or spending.
      </p>
      <p>
        If you connect from a phone, the connection is relayed through
        WalletConnect&rsquo;s servers, which see your wallet address and this
        app&rsquo;s name in order to pair the two. The signature request itself
        goes to your wallet, not to them.
      </p>
      <p>
        Be clear-eyed about what an address is, though. It is not anonymous. It
        is a durable identifier, it is the same address everywhere you use it,
        and anyone — including us — can look up its entire transaction history on
        a public blockchain. If that address is linked to your identity anywhere
        else, it is effectively linked here too. It is also personal data in
        several jurisdictions, and we treat it as such. If you would rather not
        make that connection, use a wallet you keep for this purpose, or do not
        use strategy rules — the charts and analysis need no wallet at all.
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
        Mostly market data: candles fetched from the public market API, and
        chart annotations recorded against a trading symbol. None of it is
        attached to a person, because we have no concept of a person — there are
        no accounts to attach it to.
      </p>
      <p>
        The exception is strategy rules. If you arm one, we store the rule you
        built and the history of times it fired, on our server, so it can keep
        being evaluated while your browser is closed. Each rule is stored against
        the wallet address that created it, and only that address can read,
        change or delete it. That is a deliberate change from how this feature
        first shipped, when rules were grouped under a random identifier the
        browser generated — an identifier anyone could copy and use, which is why
        it is gone.
      </p>
      <p>
        Signing in leaves a session token in your browser's local storage. It
        lasts seven days, it only permits reading and editing your own rules, and
        signing out or clearing site data removes it.
      </p>

      <h2>Who else is involved</h2>
      <ul>
        <li>
          <strong>Binance public market data API</strong> — where price candles
          come from. Requests are made by our server, not your browser, so your
          browser is not talking to them directly.
        </li>
        <li>
          <strong>Groq</strong> — runs the language model behind the chat
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
        analysis. Strategy rules and their fire history are kept until you
        delete the rule, which also deletes its history. Server logs are kept
        for a short operational period and then rotate away. Sign-in challenges
        live for five minutes and are discarded the moment they are used.
      </p>

      <h2>Your rights</h2>
      <p>
        Depending on where you live you may have rights to access, correct or
        delete personal data held about you. If you have never armed a strategy
        rule, the honest answer is that we hold nothing to look up. If you have,
        the data is your wallet address and the rules under it: you can delete any
        rule from the panel at any time, which removes it and its fire history. To
        have the address itself removed, or if you believe we hold anything else
        about you, write to{" "}
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
        If this policy changes we will update the date at the top. The team is
        small enough that we will not pretend to run a formal notification
        process.
      </p>

      <h2>Contact</h2>
      <p>
        VibeTrading is operated by its founders, {FOUNDERS_SENTENCE}, while the
        company is being incorporated. Privacy questions go to{" "}
        <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
      </p>
    </>
  )
}
