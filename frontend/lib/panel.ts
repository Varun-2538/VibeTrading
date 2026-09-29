/*
 * The header's nav reaches into the strategy panel without either owning the
 * other: the header announces where it wants to go, the panel decides what
 * that means for its own tabs and sheets. Same shape as TRADE_MARKS_EVENT.
 */
export const PANEL_NAV_EVENT = "vt:panel-nav"

export type PanelTarget = "build" | "armed" | "tests" | "vault"

export function navigatePanel(target: PanelTarget) {
  window.dispatchEvent(new CustomEvent<PanelTarget>(PANEL_NAV_EVENT, { detail: target }))
}
