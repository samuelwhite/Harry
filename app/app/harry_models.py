from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class DiskFact(BaseModel):
    name: str
    size_gb: Optional[float] = None
    type: Optional[str] = None
    serial: Optional[str] = None
    smart_power_on_hours: Optional[float] = None


class DiskUsed(BaseModel):
    mount: str
    used_pct: float
    fs: Optional[str] = None
    size_gb: Optional[float] = None


class Facts(BaseModel):
    hostname: Optional[str] = None
    model: Optional[str] = None
    cpu: Optional[str] = None
    cpu_cores: Optional[int] = None
    ram_total_gb: Optional[int] = None
    ram_max_gb: Optional[int] = None
    ram_slots_total: Optional[int] = None
    ram_slots_used: Optional[int] = None
    ram_type: Optional[str] = None
    bios_release_date: Optional[str] = None
    disks: List[DiskFact] = Field(default_factory=list)
    gpus: List[Dict[str, Any]] = Field(default_factory=list)
    extensions: Dict[str, Any] = Field(default_factory=dict)


class Metrics(BaseModel):
    cpu_load_1m: Optional[float] = None
    mem_used_pct: Optional[float] = None
    disk_used: List[DiskUsed] = Field(default_factory=list)
    temps_c: Dict[str, Any] = Field(default_factory=dict)
    gpu: List[Dict[str, Any]] = Field(default_factory=list)
    extensions: Dict[str, Any] = Field(default_factory=dict)


class Derived(BaseModel):
    health: Dict[str, Any] = Field(
        default_factory=lambda: {"state": "unknown", "worst_severity": "unknown", "reasons": []}
    )
    extensions: Dict[str, Any] = Field(default_factory=dict)


class HarrySnapshot(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: str
    agent_version: Optional[str] = None
    agent_status: Dict[str, Any] = Field(default_factory=dict)
    node: str
    ts: str
    facts: Facts = Field(default_factory=Facts)
    metrics: Metrics = Field(default_factory=Metrics)
    derived: Derived = Field(default_factory=Derived)
    advice: List[Dict[str, Any]] = Field(default_factory=list)
