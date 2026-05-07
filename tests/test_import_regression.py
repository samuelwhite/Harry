from __future__ import annotations

import importlib
import sys


def _purge(prefixes: tuple[str, ...]) -> None:
    to_remove = [name for name in sys.modules if name == prefixes[0] or name.startswith(prefixes)]
    for name in to_remove:
        sys.modules.pop(name, None)


def test_import_app_main_cleanly():
    _purge(("app.main", "app.service_awareness", "app.db_helpers", "app.ui"))
    module = importlib.import_module("app.main")
    assert module.__name__ == "app.main"


def test_import_service_awareness_cleanly():
    _purge(("app.service_awareness", "app.db_helpers"))
    module = importlib.import_module("app.service_awareness")
    assert module.__name__ == "app.service_awareness"
