from __future__ import annotations

from argparse import Namespace

from hapa_drama_node.cli import build_synthesize_command, main


def test_cli_synthesize_uses_standard_command_envelope():
    args = Namespace(
        text="hello",
        script=None,
        command_id="cmd-1",
        actor="cli:test",
        mode="flow",
        voice_id="voice-1",
        emotion_style="neutral",
        emotion_intensity=0.2,
        bpm=120.0,
        start_seconds=0.0,
        target_duration_seconds=None,
        no_card=False,
        no_cymatica=False,
    )
    command = build_synthesize_command(args)
    assert command["api_version"] == "v1"
    assert command["command_id"] == "cmd-1"
    assert command["kind"] == "synthesize"
    assert command["mode"] == "flow"
    assert command["payload"]["text"] == "hello"
    assert command["provenance"]["surface"] == "cli"


def test_cli_docs_prints_readme(capsys):
    code = main(["docs"])
    captured = capsys.readouterr()
    assert code == 0
    assert "# Hapa Drama" in captured.out
