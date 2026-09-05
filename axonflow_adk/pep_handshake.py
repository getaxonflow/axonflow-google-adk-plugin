"""The ADR-065 PEP capability handshake, client side.

Tracking: getaxonflow/axonflow-enterprise#3763.

The plugin tells the platform WHAT IT CAN DISCHARGE, on every governed call, as
a base64url-encoded JSON document in one request header. A platform that would
attach a mandatory obligation this plugin has declared it cannot carry out
DENIES the request, rather than handing over the content and trusting the plugin
to cope (ADR-065 invariant 8).

THIS PLUGIN IS TWO ENFORCEMENT POINTS, AND DECLARES ITSELF AS TWO
-----------------------------------------------------------------

The design's per-request carrier exists because one process can run two
enforcement points with different capabilities behind one credential (the
gateway adapters are the case it cites). This plugin is such a case, and one
declaration covering both paths would misdescribe one of them:

* The RESPONSE path discharges a redaction. ``_check_tool_output`` reads the
  platform's ``redacted_message`` and round-trips it back into the tool result,
  so the masked payload is what reaches the agent. It declares
  ``field_redact@1``.

* The REQUEST path does not. ``_check_tool_input`` returns ``None`` on an allow,
  which lets the original ``tool_args`` proceed unchanged; it performs no
  substitution. ADR-056 forbids the plugin from redacting for itself, so
  substitution is the only sanctioned discharge and this path does not perform
  it. It declares NOTHING.

A declaration must describe what a path CAN do rather than what it should do.
Declaring ``field_redact`` on the request path would tell the platform to ALLOW
the call on the strength of a substitution that path does not perform.

The two documents carry different ``pep_id`` values, so the platform composes
two distinguishable identifiers inside the namespace it owns and neither path is
credited with the other's capability.

WHY THIS RE-IMPLEMENTS AN ENCODER THAT EXISTS
---------------------------------------------

The canonical encoder is ``contract.PEPHandshake.Encode`` in a PRIVATE
repository this public one cannot import, so this module is a hand transcription
of a wire format - the drift class that bit five SDKs in
axonflow-enterprise#3603. The mitigation is not care: ``tests/test_pep_handshake.py``
asserts the exact bytes against vectors captured from the platform's own shipped
encoder.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass

#: The request header a declaration rides on.
PEP_HANDSHAKE_HEADER = "X-Axonflow-PEP-Handshake"

#: The only profile this build emits. The platform matches it with EXACT
#: equality, never as a floor or a range: a build that cannot emit the named
#: profile must not answer as though negotiation succeeded.
PROFILE_VERSION = 1

#: The obligation type for engine-fulfilled redaction, and its schema version.
CAP_FIELD_REDACT = "field_redact"
CAP_SCHEMA_V1 = 1

#: The two enforcement point names, inside the caller's credential namespace.
#:
#: Neither carries a colon: the platform composes
#: ``client:<credential>:<pep_id>``, so admitting one would let a name appear
#: inside an identifier that no string search could tell apart from a real
#: in-process plane.
PEP_ID_REQUEST = "adk-request"
PEP_ID_RESPONSE = "adk-response"

#: The platform refuses a header value longer than this.
MAX_HANDSHAKE_BYTES = 4096

#: Bounds the operator-supplied audience before it can reach the wire, so a
#: malformed value fails at construction rather than 400-ing every governed call
#: in production.
# `\Z` rather than `$`, and that is not style: Python's `$` also matches just
# BEFORE a trailing newline, so `^...$` accepts "aud\n" - which the platform
# refuses, because its own grammar is anchored to the end of the string. A
# newline-terminated audience would then be built here and 400 every governed
# call. Caught by test_a_malformed_audience_raises_rather_than_silently_disabling.
_AUDIENCE_PATTERN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:-]*\Z")


@dataclass(frozen=True)
class PepHandshakes:
    """The two declarations this plugin presents."""

    #: Presented on the request-phase governed call.
    request: str
    #: Presented on the response-phase governed call.
    response: str


def encode_handshake(pep_id: str, audience: str, capabilities: list[dict[str, object]]) -> str:
    """Render one declaration as the header value.

    Raises ``ValueError`` on a malformed audience or an over-long document,
    rather than returning an empty string: a value that silently disabled the
    handshake would leave an operator believing a control was in force when it
    was not.
    """
    if not 1 <= len(audience) <= 128 or not _AUDIENCE_PATTERN.match(audience):
        raise ValueError(
            f"invalid AxonFlow PEP audience {audience!r}: "
            f"1-128 bytes matching {_AUDIENCE_PATTERN.pattern}"
        )

    # Canonical (type, version) order so two installs declaring the same set in
    # a different order send the same bytes. The platform sorts too; agreeing
    # here is what makes the encoding reproducible and the golden vector
    # meaningful.
    ordered = sorted(capabilities, key=lambda c: (str(c["type"]), int(c["version"])))  # type: ignore[index]

    doc = {
        "profile_version": PROFILE_VERSION,
        "pep_id": pep_id,
        "audience": audience,
        # ALWAYS serialised, never omitted when empty. An OMITTED
        # `capabilities` member is MALFORMED to the platform and refuses the
        # request, while `[]` is the legitimate declaration "I discharge
        # nothing" - different facts with different outcomes.
        "capabilities": ordered,
    }
    # separators without spaces so the bytes match the platform's compact
    # encoding; the key order is the insertion order above.
    raw = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    if len(encoded) > MAX_HANDSHAKE_BYTES:
        raise ValueError(
            f"the AxonFlow PEP capability handshake encodes to {len(encoded)} bytes; "
            f"the header carries at most {MAX_HANDSHAKE_BYTES}"
        )
    return encoded


def build_pep_handshakes(audience: str | None) -> PepHandshakes | None:
    """Build both declarations, or ``None`` when no audience is configured.

    WHY AN AUDIENCE IS REQUIRED RATHER THAN DEFAULTED

    The audience is what a decision proof gets bound to and only the DEPLOYMENT
    knows it; a plugin that invented one would assert a binding nobody asked
    for. It is also why the handshake is opt-in: on an Enterprise platform the
    transition it gates on the REQUEST path is ALLOW -> DENY, because that path
    performs no substitution. ``None`` here means no header, and the plugin then
    behaves byte for byte as it did before.

    Same knob name and semantics as every other AxonFlow client
    (``AXONFLOW_PEP_AUDIENCE``), deliberately: one contract across the fleet, no
    per-client dialects.
    """
    if not audience:
        return None
    return PepHandshakes(
        # The request path performs no substitution, so it declares nothing.
        request=encode_handshake(PEP_ID_REQUEST, audience, []),
        # The response path round-trips the platform's redacted_message back
        # into the tool result, so it does discharge the obligation.
        response=encode_handshake(
            PEP_ID_RESPONSE, audience, [{"type": CAP_FIELD_REDACT, "version": CAP_SCHEMA_V1}]
        ),
    )
