"""Every governed call this integration makes must say what it is.

Before this, calls from `axonflow_mcp_toolset` reached the platform carrying no
identity at all: ADK adoption was invisible to the client-version counter, the
checkpoint pipeline and the Community-SaaS stream at once, and indistinguishable
from an anonymous caller. See enterprise#3672.

These drive the REAL helper and read the headers it actually hands to the ADK
connection params - nothing is reconstructed here.
"""

from __future__ import annotations

import re

import pytest

from axonflow_adk._version import __version__
from axonflow_adk.mcp_helper import (
    AXONFLOW_CLIENT_HEADER,
    AXONFLOW_CLIENT_VALUE,
    axonflow_mcp_toolset,
)


def _headers(toolset) -> dict[str, str]:
    """The headers the toolset will actually send.

    Read off the connection params the REAL helper built. The ADK boundary is
    stubbed in `conftest.py` on the same terms as the rest of this suite; the
    decision under test is which headers the helper hands over, and that is
    entirely ours.
    """
    return dict(toolset.connection_params.headers or {})


def test_header_is_sent_on_an_anonymous_community_call() -> None:
    # The anonymous case matters most: with no Authorization header there was
    # previously nothing at all on the request to attribute it.
    headers = _headers(axonflow_mcp_toolset("http://localhost:8080"))
    assert headers[AXONFLOW_CLIENT_HEADER] == f"google-adk-plugin/{__version__}"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"client_id": "acme", "client_secret": "s3cret"},
        {"bearer_token": "tok"},
    ],
)
def test_header_rides_every_auth_shape(kwargs: dict[str, str]) -> None:
    headers = _headers(axonflow_mcp_toolset("http://localhost:8080", **kwargs))
    assert headers[AXONFLOW_CLIENT_HEADER] == AXONFLOW_CLIENT_VALUE
    # ...without displacing the header the platform actually authenticates on.
    assert "Authorization" in headers


def test_extra_headers_cannot_replace_the_client_identity() -> None:
    # `extra_headers` is documented for tenant scoping and tracing context. It
    # is merged BEFORE the identity is applied, so a caller cannot make this
    # integration claim to be something else.
    headers = _headers(
        axonflow_mcp_toolset(
            "http://localhost:8080",
            extra_headers={AXONFLOW_CLIENT_HEADER: "something-else/9.9.9"},
        )
    )
    assert headers[AXONFLOW_CLIENT_HEADER] == AXONFLOW_CLIENT_VALUE


def test_extra_headers_still_work_for_everything_else() -> None:
    headers = _headers(
        axonflow_mcp_toolset(
            "http://localhost:8080",
            extra_headers={"X-Tenant-Id": "acme"},
        )
    )
    assert headers["X-Tenant-Id"] == "acme"
    assert headers[AXONFLOW_CLIENT_HEADER] == AXONFLOW_CLIENT_VALUE


def test_value_shape_matches_what_the_platform_parses() -> None:
    # The engine splits on the LAST "/" (ParseClient) and the checkpoint's
    # validator holds a closed allowlist of ids. An id it does not know is
    # dropped SILENTLY, so this pins the exact string rather than reading the
    # constant back - a rename has to be a deliberate edit here, paired with
    # the server-side allowlist (enterprise#3672).
    assert re.fullmatch(
        r"google-adk-plugin/[0-9]+\.[0-9]+\.[0-9]+[0-9A-Za-z.+-]*",
        AXONFLOW_CLIENT_VALUE,
    ), AXONFLOW_CLIENT_VALUE


def test_version_comes_from_package_metadata_not_a_literal() -> None:
    assert AXONFLOW_CLIENT_VALUE.endswith(f"/{__version__}")
