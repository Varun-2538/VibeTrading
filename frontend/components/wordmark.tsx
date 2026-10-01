export default function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-baseline gap-2 ${className}`}>
      {/* The mark is a candle body with its wick - the smallest unit of the subject */}
      <svg width="11" height="18" viewBox="0 0 11 18" aria-hidden className="translate-y-[2px]">
        <line x1="5.5" y1="0" x2="5.5" y2="18" stroke="var(--vt-mint)" strokeWidth="1.25" />
        <rect
          x="0.75"
          y="4.5"
          width="9.5"
          height="9"
          fill="var(--vt-void)"
          stroke="var(--vt-mint)"
          strokeWidth="1.25"
        />
      </svg>
      <span
        className="font-display text-[17px] font-extrabold tracking-[-0.02em]"
        style={{ color: "var(--vt-ink)" }}
      >
        vibetrading
      </span>
    </span>
  )
}
