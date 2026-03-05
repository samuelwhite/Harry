# /opt/harry/brain/app/app/rules.py
from __future__ import annotations

from typing import Any, Dict, List

# Canonical engine lives here
from app.advice_engine import build_advice_and_health


def _map_level(sev: str) -> str:
    """
    Map advice_engine severities to UI-friendly ones.
    UI expects: ok | info | warn | bad
    advice_engine uses: info | warn | crit
    """
    s = (sev or "info").lower().strip()
    if s in ("crit", "critical", "bad", "red"):
        return "bad"
    if s in ("warn", "warning", "amber"):
        return "warn"
    if s in ("info", "green"):
        return "info"
    return "info"


def evaluate(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Compatibility wrapper used by ui.py.

    Returns list of dicts with:
      - severity: ok | info | warn | bad
      - message: short human text (UI uses this)
      - code: stable identifier
      - recommendation: optional (kept for future UI)
      - evidence: optional (kept for debug)
      - confidence: optional
      - category: optional
      - field/value: optional (extra debug convenience)
    """
    advice, _health = build_advice_and_health(snapshot or {})

    out: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for a in advice:
        if not isinstance(a, dict):
            continue

        code = str(a.get("id") or a.get("code") or "").strip() or "advice"
        if code in seen:
            continue
        seen.add(code)

        sev = _map_level(str(a.get("severity") or "info"))

        msg = str(a.get("message") or "").strip()
        rec = str(a.get("recommendation") or "").strip()

        # Keep the UI punchy: combine message + recommendation (as before)
        combined = msg
        if rec:
            combined = f"{msg} — {rec}" if msg else rec

        if not combined:
            continue

        out.append(
            {
                "severity": sev,
                "message": combined,
                "code": code,
                "category": a.get("category"),
                "confidence": a.get("confidence"),
                "recommendation": rec or None,
                "evidence": a.get("evidence") or {},
                # optional debug hints (engine already includes these in evidence/value sometimes)
                "field": a.get("field") if "field" in a else "",
                "value": a.get("value") if "value" in a else None,
            }
        )

    return out
