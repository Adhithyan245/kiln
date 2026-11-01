"""Original cached-artifact replay component; no model, GPU or Streamlit dependency."""
from __future__ import annotations

import html

RISK_WORDS = {"red": "High risk", "amber": "Watch", "green": "Go", "inconclusive": "Inconclusive"}
STAMPS = {"accepted": "Accepted", "rejected": "Rejected · dropped from verdict",
          "inconclusive": "Inconclusive", "pending": "Awaiting verifier"}
AGENT_LABELS = {"precursor": "Precursor", "thermo": "Thermo", "kinetics": "Kinetics",
                "single": "Single agent", "planner": "Planner", "skeptic": "Skeptic"}


def _agent_title(raw: str | None) -> str:
    if not raw:
        return "Specialist"
    return AGENT_LABELS.get(str(raw).strip().lower(), str(raw))


def render_evidence_strip(artifacts: list[dict], risk_before: str | None, risk_after: str | None,
                          replayed: bool = True, *, prefix: str = "trail") -> str:
    """One linked segment per artifact, already in the adapter's provenance order.

    A risk transition needs explicit risk values AND accepted evidence answering a need.
    Missing risk stays unknown; outcomes are never translated into new risk categories.
    """
    esc = lambda value: html.escape(str(value), quote=True)
    segments = []
    counts = {"accepted": 0, "rejected": 0, "inconclusive": 0, "pending": 0}
    for i, artifact in enumerate(artifacts):
        status = artifact.get("verifier", "inconclusive")
        status = status if status in STAMPS else "inconclusive"
        counts[status] = counts.get(status, 0) + 1
        need = bool(artifact.get("fulfills_need")) and status == "accepted"
        values = artifact.get("values") if isinstance(artifact.get("values"), dict) else {}
        tier = values.get("compute_tier")
        tier_html = (f'<span class="segment-tier">{esc(str(tier).replace("_", " "))}</span>'
                     if tier and tier != "skipped" else "")
        segments.append(
            f'<li class="strip-segment" data-status="{status}" data-step="{i}" style="--seg-index:{i}">'
            f'<a href="#{esc(prefix)}-artifact-{i}" class="segment-link">'
            '<span class="segment-heat" aria-hidden="true"></span>'
            '<span class="segment-top">'
            f'<span class="segment-step">{i + 1:02d}</span>'
            f'<span class="segment-agent">{esc(_agent_title(artifact.get("agent")))}</span>'
            f'{tier_html}</span>'
            f'<span class="segment-summary">{esc(artifact.get("summary") or "Recorded evidence")}</span>'
            '<span class="segment-foot">'
            f'<span class="segment-stamp">{STAMPS[status]}</span>'
            + ('<span class="segment-need">Answered an agent request</span>' if need else '')
            + '</span></a></li>')
    changed = (risk_before in RISK_WORDS and risk_after in RISK_WORDS and risk_before != risk_after
               and any(a.get("fulfills_need") and a.get("verifier") == "accepted" for a in artifacts))
    before = (f'<span class="risk-pill risk-{risk_before}">{RISK_WORDS[risk_before]}</span>'
              '<span class="transition-arrow" aria-label="changed to">→</span>') if changed else ''
    after = (f'<span class="risk-pill risk-{risk_after}">{RISK_WORDS[risk_after]}</span>'
             if risk_after in RISK_WORDS else '<span class="risk-pill risk-inconclusive">Risk not recorded</span>')
    because = ('<p class="change-reason">Changed because one agent answered another agent’s request.</p>'
               if changed else '')
    disabled = '' if artifacts else ' disabled'
    tally = (f'<span class="strip-tally">'
             f'<span class="tally-chip tally-accepted">{counts["accepted"]} accepted</span>'
             + (f'<span class="tally-chip tally-rejected">{counts["rejected"]} rejected</span>' if counts["rejected"] else '')
             + (f'<span class="tally-chip tally-inconclusive">{counts["inconclusive"] + counts["pending"]} inconclusive</span>'
                if (counts["inconclusive"] + counts["pending"]) else '')
             + '</span>') if artifacts else '<span class="strip-tally"><span class="tally-chip">0 artifacts</span></span>'
    return ('<div class="evidence-strip" data-replay>'
            '<div class="strip-toolbar"><div class="strip-title-group">'
            '<span class="strip-eyebrow"><i class="furnace-dot" aria-hidden="true"></i>Furnace verification bar · provenance order</span>'
            '<h3>Evidence strip</h3>'
            '<p>Follow each artifact through verification. Select a segment to inspect its source card below.</p></div>'
            f'<div class="strip-controls">{tally}<div class="strip-button-group" role="group" aria-label="Replay controls">'
            f'<button type="button" class="button button-ghost step-prev"{disabled} title="Step back">‹ Step</button>'
            f'<button type="button" class="button button-ghost step-next"{disabled} title="Step forward">Step ›</button>'
            f'<button type="button" class="button button-primary play-trail"{disabled}>▶ Play trail</button>'
            '</div></div></div>'
            '<div class="strip-meta-bar">'
            '<p class="replay-note">' + ('Replayed from cached runs.' if replayed else 'Recorded evidence.') + '</p>'
            '<span class="strip-legend" aria-hidden="true">'
            '<span class="legend-item"><i class="legend-swatch swatch-accepted"></i>Accepted</span>'
            '<span class="legend-item"><i class="legend-swatch swatch-rejected"></i>Rejected · dropped</span>'
            '<span class="legend-item"><i class="legend-swatch swatch-inconclusive"></i>Inconclusive</span>'
            '</span></div>'
            '<ol class="strip-segments">' + ''.join(segments) + '</ol>'
            '<div class="strip-verdict" role="status" aria-live="polite"><span>Kiln proposes</span>'
            + before + after + because + '</div></div>')
