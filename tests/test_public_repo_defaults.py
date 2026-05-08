from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".yml",
    ".yaml",
    ".ps1",
    ".sh",
    ".iss",
    ".xml",
    ".css",
    ".js",
    ".html",
}
BLOCKED = [
    "white" + " family",
    "white" + "family" + "home",
    "harry." + "white" + "family" + "home.net",
    "192.168." + "7" + ".",
    "desk" + "top" + "-" + "sa" + "m",
    "samsungjultokluno" + "pate",
]


def test_public_repo_has_no_private_reference_strings():
    offenders: list[str] = []

    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in {".git", ".pytest_cache", ".pytest-tmp", "tmp_pytest", "tmp_pytest_full", "tmp_pytest_post"} for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue

        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for blocked in BLOCKED:
            if blocked in text:
                offenders.append(f"{path.relative_to(ROOT)} -> {blocked}")

    assert offenders == []
