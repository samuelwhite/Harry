from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, List, Optional


class Severity(IntEnum):
    NONE = 0
    INFO = 1
    WARN = 2
    CRITICAL = 3


@dataclass(frozen=True)
class Advice:
    category: str
    severity: Severity
    title: str
    message: str
    code: str = ""
    data: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class NodeState:
    node: str
    ts_iso: str
    ts_human: str
    ts_relative: str
    status: str
    status_severity: Severity
    facts: Dict[str, Any]
    metrics: Dict[str, Any]
    derived: Dict[str, Any]
    advice: List[Advice]
