from __future__ import annotations

import json

from fastapi import HTTPException

from .db import get_latest_node_record, _clamp, DUMP_DEFAULT_HOURS, _raw_payload
from .templates import _html_escape, page_html


def render_node_detail(node: str, hours: int) -> str:
    row = get_latest_node_record(node.strip())
    if not row:
        raise HTTPException(status_code=404, detail="not_found")

    try:
        payload = json.loads(row["payload"])
    except Exception:
        payload = {"bad_payload": True, "raw": row["payload"]}

    raw = _raw_payload(payload)

    pretty_payload = _html_escape(json.dumps(payload, indent=2, ensure_ascii=False))
    pretty_raw = _html_escape(json.dumps(raw, indent=2, ensure_ascii=False)) if raw else "—"

    body = f"""
<div class="h1">{_html_escape(node)}</div>
<div class="sub">
  <span>{_html_escape(row["ts"])}</span>
  <span>•</span>
  <a href="/?hours={hours}">Fleet</a>
  <span>•</span>
  <a href="/inventory">Inventory</a>
  <span>•</span>
  <a href="/diagnostics?hours={hours}">Diagnostics</a>
  <span>•</span>
  <a href="/debug/latest/{_html_escape(node)}">debug/latest</a>
  <span>•</span>
  <a href="/dump?hours={hours}">dump?hours={hours}</a>
</div>

<div class="panel">
  <div style="font-weight:900; margin-bottom:10px;">Normalised payload (stored in DB)</div>
  <pre style="margin:0; padding:12px; border-radius:12px; overflow:auto; background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.08); font-size:12px; line-height:1.35;">{pretty_payload}</pre>
</div>

<div class="panel">
  <div style="font-weight:900; margin-bottom:10px;">Raw payload (if captured)</div>
  <pre style="margin:0; padding:12px; border-radius:12px; overflow:auto; background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.08); font-size:12px; line-height:1.35;">{pretty_raw}</pre>
</div>
"""
    return page_html(f"HARRY • {node}", body)

