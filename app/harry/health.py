from __future__ import annotations

from typing import List, Tuple

from .models import Advice, Severity


def aggregate_status(advice: List[Advice]) -> Tuple[str, Severity]:
    max_sev = Severity.NONE
    for a in advice:
        if a.severity > max_sev:
            max_sev = a.severity

    if max_sev >= Severity.CRITICAL:
        return "red", max_sev
    if max_sev >= Severity.WARN:
        return "amber", max_sev
    return "green", max_sev
