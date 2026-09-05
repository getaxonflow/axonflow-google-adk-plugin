"""The ADR-065 PEP capability handshake for this plugin.

Tracking: getaxonflow/axonflow-enterprise#3763.

GOLDEN VECTORS CAPTURED FROM THE PLATFORM'S OWN SHIPPED ENCODER
(``contract.PEPHandshake.Encode``), not regenerated from this module's output.
This repository cannot import the contract package - it lives in a private repo
- so ``pep_handshake.py`` is a hand transcription of a wire format, the drift
class that bit five SDKs in axonflow-enterprise#3603. A test that built its
expectation by calling ``build_pep_handshakes`` would agree with whatever that
function did, including being wrong.
"""

import base64
import json

import pytest

from axonflow_adk.pep_handshake import (
    PEP_HANDSHAKE_HEADER,
    PEP_ID_REQUEST,
    PEP_ID_RESPONSE,
    build_pep_handshakes,
    encode_handshake,
)

GOLDEN_REQUEST = "eyJwcm9maWxlX3ZlcnNpb24iOjEsInBlcF9pZCI6ImFkay1yZXF1ZXN0IiwiYXVkaWVuY2UiOiJheG9uZmxvdy1kZWNpc2lvbi1wcm9vZiIsImNhcGFiaWxpdGllcyI6W119"
GOLDEN_RESPONSE = "eyJwcm9maWxlX3ZlcnNpb24iOjEsInBlcF9pZCI6ImFkay1yZXNwb25zZSIsImF1ZGllbmNlIjoiYXhvbmZsb3ctZGVjaXNpb24tcHJvb2YiLCJjYXBhYmlsaXRpZXMiOlt7InR5cGUiOiJmaWVsZF9yZWRhY3QiLCJ2ZXJzaW9uIjoxfV19"
AUDIENCE = "axonflow-decision-proof"


def _decode(encoded: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))


def test_encoding_matches_the_platform_encoder_byte_for_byte():
    hs = build_pep_handshakes(AUDIENCE)
    assert hs is not None
    assert hs.request == GOLDEN_REQUEST
    assert hs.response == GOLDEN_RESPONSE


def test_the_request_path_declares_nothing():
    # _check_tool_input returns None on an allow, letting the original
    # tool_args proceed; it performs no substitution. Declaring field_redact
    # would tell the platform to ALLOW on the strength of a substitution this
    # path does not perform.
    doc = _decode(build_pep_handshakes(AUDIENCE).request)
    assert doc["capabilities"] == []
    assert doc["pep_id"] == PEP_ID_REQUEST


def test_the_response_path_declares_field_redact_because_it_substitutes():
    # _check_tool_output round-trips the platform's redacted_message back into
    # the tool result, so it does discharge the obligation.
    doc = _decode(build_pep_handshakes(AUDIENCE).response)
    assert doc["capabilities"] == [{"type": "field_redact", "version": 1}]
    assert doc["pep_id"] == PEP_ID_RESPONSE


def test_the_two_paths_are_distinguishable():
    hs = build_pep_handshakes(AUDIENCE)
    assert hs.request != hs.response
    # The platform composes client:<credential>:<pep_id>, so a colon would let
    # a name appear inside an identifier no string search could tell from a
    # real in-process plane.
    assert ":" not in PEP_ID_REQUEST
    assert ":" not in PEP_ID_RESPONSE


def test_an_empty_declaration_serialises_as_an_empty_array():
    # An OMITTED capabilities member is MALFORMED to the platform and refuses
    # the request; [] is the declaration "I discharge nothing".
    raw = base64.urlsafe_b64decode(
        build_pep_handshakes(AUDIENCE).request + "=="
    ).decode()
    assert '"capabilities":[]' in raw


def test_no_identity_or_entitlement_member_reaches_the_wire():
    # A PEP may declare what it CAN DO, never who it is or what it is entitled
    # to, and the platform refuses an unknown member outright.
    for encoded in (build_pep_handshakes(AUDIENCE).request, build_pep_handshakes(AUDIENCE).response):
        assert set(_decode(encoded)) == {"profile_version", "pep_id", "audience", "capabilities"}


def test_no_audience_presents_nothing_at_all():
    assert build_pep_handshakes(None) is None
    assert build_pep_handshakes("") is None


@pytest.mark.parametrize("bad", ["has spaces", "-leading-hyphen", "a" * 129, "trailing\n"])
def test_a_malformed_audience_raises_rather_than_silently_disabling(bad):
    # A value that quietly disabled the handshake would leave an operator
    # believing a control was in force when it was not.
    with pytest.raises(ValueError):
        encode_handshake(PEP_ID_REQUEST, bad, [])


def test_capabilities_are_sorted_canonically():
    a = encode_handshake("p", AUDIENCE, [
        {"type": "immutable_audit", "version": 1},
        {"type": "field_redact", "version": 1},
    ])
    b = encode_handshake("p", AUDIENCE, [
        {"type": "field_redact", "version": 1},
        {"type": "immutable_audit", "version": 1},
    ])
    assert a == b


def test_the_header_is_named_exactly_as_the_platform_reads_it():
    assert PEP_HANDSHAKE_HEADER == "X-Axonflow-PEP-Handshake"
