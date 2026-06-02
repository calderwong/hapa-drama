from __future__ import annotations

from hapa_drama_node.engines.mlx_audio_adapter import _payload_ref_text


def test_profile_reference_note_is_not_treated_as_ref_text():
    payload = {
        "voice_profile": {
            "request_hints": {
                "reference_text": "Browser microphone voice sample recorded in Hapa Drama.",
            }
        }
    }

    assert _payload_ref_text(payload, None) is None


def test_profile_reference_transcript_can_be_marked_explicitly():
    payload = {
        "voice_profile": {
            "request_hints": {
                "reference_text": "This is the exact sentence spoken in the sample.",
                "reference_text_is_transcript": True,
            }
        }
    }

    assert _payload_ref_text(payload, None) == "This is the exact sentence spoken in the sample."


def test_direct_payload_ref_text_still_passes_through():
    assert _payload_ref_text({"ref_text": "exact reference caption"}, None) == "exact reference caption"
