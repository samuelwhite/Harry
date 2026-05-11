from __future__ import annotations

import argparse
import shutil
from pathlib import Path


WINDOWS_FILES = [
    "README.txt",
    "START-HERE.txt",
    "agent_config.sample.json",
    "harry_agent.exe",
    "diagnose.ps1",
    "install_agent.ps1",
    "update_agent.ps1",
    "uninstall_agent.ps1",
    "HarryAgentService.exe",
    "HarryAgentService.xml",
]


def _copy_tree(source_dir: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    for name in WINDOWS_FILES:
        src = source_dir / name
        if not src.exists() or not src.is_file():
            continue
        shutil.copy2(src, dest_dir / name)


def sync_windows_artifacts(root: Path) -> None:
    source = root / "agent" / "windows"
    dist = root / "app" / "dist" / "windows"
    agent_payload = root / "installers" / "windows" / "payload"
    brain_payload = root / "installers" / "windows" / "brain-payload" / "_internal" / "dist" / "windows"

    if not source.exists():
        raise FileNotFoundError(f"Windows agent source not found: {source}")

    for target in (dist, agent_payload, brain_payload):
        _copy_tree(source, target)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Windows installer/runtime artifacts from agent/windows.")
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root directory.",
    )
    args = parser.parse_args()
    sync_windows_artifacts(Path(args.root).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
