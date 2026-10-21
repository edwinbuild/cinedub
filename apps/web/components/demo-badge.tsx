/** Visible marker for deterministic DEMO provider output. It is never quality evidence. */
export function DemoBadge({ label = "DEMO", title = "Deterministic DEMO fixture output, not a model result or quality evidence" }: { label?: string; title?: string }) {
  return <span className="demoBadge" title={title}>{label}</span>;
}
