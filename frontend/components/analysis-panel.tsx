export default function AnalysisPanel() {
  return (
    <div className="flex h-full w-full flex-col bg-card">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-border px-3 py-3 lg:px-4">
        <h2 className="text-sm font-semibold text-foreground">Analysis Panel</h2>
        <span className="text-xs text-muted-foreground">Coming Soon</span>
      </div>

      {/* Empty state. Flex rather than a hard-coded header height, which was
          only ever right at one type size. */}
      <div className="flex min-h-0 flex-1 items-center justify-center px-6 py-6">
        <div className="text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-secondary">
            <svg className="h-8 w-8 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
              />
            </svg>
          </div>
          <h3 className="mb-1 text-sm font-medium text-foreground">Empty Panel</h3>
          <p className="mx-auto max-w-xs text-xs leading-relaxed text-muted-foreground">
            This panel is reserved for future features like technical indicators, market depth, or order book.
          </p>
        </div>
      </div>
    </div>
  )
}
