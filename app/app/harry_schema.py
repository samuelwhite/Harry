import json
from pathlib import Path
from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "harry" / "current.json"

_SCHEMA = json.loads(SCHEMA_PATH.read_text())
_VALIDATOR = Draft202012Validator(_SCHEMA)


def validate_harry_snapshot(payload: dict) -> list[str]:
    errors = sorted(_VALIDATOR.iter_errors(payload), key=lambda e: e.path)
    out: list[str] = []
    for e in errors:
        path = ".".join(map(str, e.path)) if e.path else "(root)"
        out.append(f"{path}: {e.message}")
    return out
