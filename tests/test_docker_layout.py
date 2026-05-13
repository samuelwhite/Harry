from __future__ import annotations

import shutil
import subprocess
import sys
import os
from pathlib import Path


def test_container_layout_imports_app_main(tmp_path):
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()

    for name in ("app", "schemas", "dist", "harry"):
        shutil.copytree(Path("app") / name, runtime_root / name)

    shutil.copy2(Path("app") / "capabilities.yml", runtime_root / "capabilities.yml")
    shutil.copy2(Path("app") / "run_brain.py", runtime_root / "run_brain.py")

    result = subprocess.run(
        [sys.executable, "-c", "import app.main; print(app.main.BRAIN_VERSION)"],
        cwd=runtime_root,
        env={**os.environ, "PYTHONPATH": str(runtime_root)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "2026.05.15" in result.stdout


def test_dockerfile_copies_package_root_not_nested_app():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "COPY app/app /app/app/" in dockerfile
    assert "COPY app/ /app/app/" not in dockerfile
    assert 'CMD ["uvicorn", "app.main:app"' in dockerfile
