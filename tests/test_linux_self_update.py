from pathlib import Path


def test_linux_agent_self_update_has_version_gate():
    script = (Path(__file__).resolve().parents[1] / "agent" / "harry_agent.sh").read_text(encoding="utf-8")

    assert "version_is_newer" in script
    assert "candidate_not_newer" in script
    assert "mktemp \"${me_dir%/}/.harry_agent.XXXXXX.sh\"" in script
