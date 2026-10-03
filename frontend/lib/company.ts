/*
 * Who and what VibeTrading is, in one place.
 *
 * The landing page and the legal pages both read from here, so the founders,
 * the stage and the roadmap can be updated without touching layout - and so
 * the same fact is never stated two different ways on two different pages.
 */

export const COMPANY = {
  name: "VibeTrading",
  founded: "2025",
  /*
   * Stated as it is. The company is being formed; nothing on the site claims
   * an entity exists before it does.
   */
  status: "Early-stage company, incorporation in progress",
  stage: "Public beta",
  socials: {
    x: "https://x.com/Vibetradingclub",
    github: "https://github.com/Varun-2538/smartTrade.ai",
  },
} as const

export interface Founder {
  name: string
  title: string
  linkedin: string
}

export const FOUNDERS: readonly Founder[] = [
  {
    name: "Varun Singh",
    title: "Co-founder",
    linkedin: "https://www.linkedin.com/in/varun2534/",
  },
  {
    name: "Vidhi Singh",
    title: "Co-founder",
    linkedin: "https://www.linkedin.com/in/vidhisingh14/",
  },
]

/** A sentence naming the founders, for prose that has to say who runs this. */
export const FOUNDERS_SENTENCE = FOUNDERS.map((f) => f.name).join(" and ")

export interface RoadmapItem {
  when: "Live" | "In testing" | "Next" | "Planned"
  title: string
  body: string
}

/*
 * Everything here is either shipped or actually in the repo. Roadmap items are
 * written as intent - what is being built - not as promises with dates.
 */
export const ROADMAP: readonly RoadmapItem[] = [
  {
    when: "Live",
    title: "Levels, patterns and strategy alerts",
    body: "Liquidity levels with test counts, W and M patterns tracked through their lifecycle, and server-side rules that alert when a condition is met - with the browser closed.",
  },
  {
    when: "In testing",
    title: "Android app on Google Play",
    body: "The phone layout packaged as an installable app. In closed testing ahead of a production listing.",
  },
  {
    when: "Next",
    title: "Alerts by push notification",
    body: "Rule signals delivered to the phone rather than only to an open tab.",
  },
  {
    when: "Planned",
    title: "Rules that act, not only alert",
    body: "Phase two of the strategy engine. Today a rule can only raise an alert; nothing places a trade.",
  },
]
