export default function AnalysisPanel() {
  return (
    <div className="h-full w-full bg-card">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold text-foreground">Analysis Panel</h2>
        <span className="text-xs text-muted-foreground">Coming Soon</span>
      </div>

      {/* Empty State */}
      <div className="flex h-[calc(100%-57px)] items-center justify-center">
        <div className="text-center">
          <div className="mx-auto mb-4 h-16 w-16 rounded-full bg-secondary flex items-center justify-center">
            <svg className="h-8 w-8 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
              />
            </svg>
          </div>
          <h3 className="text-sm font-medium text-foreground mb-1">Empty Panel</h3>
          <p className="text-xs text-muted-foreground max-w-xs">
            This panel is reserved for future features like technical indicators, market depth, or order book.
          </p>
        </div>
      </div>
    </div>
  )
}
