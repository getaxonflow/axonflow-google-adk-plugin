# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""`axonflow_mcp_toolset` must resolve against the google-adk that is installed.

The v1.2.0 release run failed with "cannot import name 'McpToolset' from
'google.adk.tools.mcp_tool'" on google-adk 2.8.0. The class had not moved;
google-adk keeps the `mcp` SDK optional, this package had never declared it,
and the unpinned `pip install mcp` the e2e used instead resolved `mcp` 2.x,
which google-adk does not support. ADK's package `__init__` swallows that
ImportError and re-raises it under the toolset's name.

Every other test in this directory runs against the stubbed ADK boundary in
`conftest.py`, and that is right for them: they test the helper's decisions.
These tests are about the OTHER side of the boundary, so they run in a
subprocess where nothing is stubbed and the resolver's answer is the real
one. They skip only when google-adk is not installed at all, which is the
stub-only configuration the rest of the suite is designed for.
"""

from __future__ import annotations

import importlib.metadata
import json
import subprocess
import sys
import textwrap

import pytest


def _installed(dist: str) -> bool:
    try:
        importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


requires_real_adk = pytest.mark.skipif(
    not _installed("google-adk"),
    reason="google-adk is not installed; this suite runs on the stubbed boundary",
)


def _run_clean(code: str) -> dict:
    """Run `code` in a fresh interpreter (no conftest stubs) and return its JSON."""
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, f"subprocess failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


@requires_real_adk
def test_toolset_import_resolves_under_the_installed_google_adk() -> None:
    # The helper's own import, run for real. Both names, from the modules
    # that define them, so a moved class or a broken `mcp` fails HERE with
    # the underlying cause rather than in the release e2e.
    out = _run_clean(
        """
        import json
        from axonflow_adk.mcp_helper import (
            ADK_MCP_SESSION_MANAGER_MODULE,
            ADK_MCP_TOOLSET_MODULE,
            _load_adk_mcp_toolset,
        )
        toolset_cls, params_cls = _load_adk_mcp_toolset()
        print(json.dumps({
            "toolset": f"{toolset_cls.__module__}.{toolset_cls.__qualname__}",
            "params": f"{params_cls.__module__}.{params_cls.__qualname__}",
            "toolset_module": ADK_MCP_TOOLSET_MODULE,
            "params_module": ADK_MCP_SESSION_MANAGER_MODULE,
        }))
        """
    )
    assert out["toolset"] == f"{out['toolset_module']}.McpToolset"
    assert out["params"] == f"{out['params_module']}.StreamableHTTPConnectionParams"


@requires_real_adk
def test_helper_constructs_a_real_toolset_with_the_headers_it_promises() -> None:
    # End to end through the public entry point, on the real classes: the
    # decisions the stubbed tests read off a capturing stub must survive
    # contact with the actual ADK constructor.
    out = _run_clean(
        """
        import json
        from axonflow_adk import axonflow_mcp_toolset
        from axonflow_adk.mcp_helper import AXONFLOW_CLIENT_HEADER, AXONFLOW_CLIENT_VALUE
        t = axonflow_mcp_toolset("http://localhost:8080/", client_id="a", client_secret="b")
        cp = t._connection_params if hasattr(t, "_connection_params") else t.connection_params
        print(json.dumps({
            "type": type(t).__name__,
            "url": cp.url,
            "auth": cp.headers.get("Authorization", ""),
            "client": cp.headers.get(AXONFLOW_CLIENT_HEADER),
            "expected_client": AXONFLOW_CLIENT_VALUE,
        }))
        """
    )
    assert out["type"] == "McpToolset"
    assert out["url"] == "http://localhost:8080/mcp/"
    assert out["auth"].startswith("Basic ")
    assert out["client"] == out["expected_client"]


@requires_real_adk
def test_installed_mcp_sdk_is_inside_the_range_the_installed_google_adk_declares() -> None:
    # The invariant that actually broke. Read from google-adk's OWN metadata
    # so this follows whatever range each ADK release supports; nothing here
    # hardcodes `<2`.
    from packaging.requirements import Requirement
    from packaging.version import Version

    reqs = importlib.metadata.requires("google-adk") or []
    mcp_specs = [
        Requirement(r)
        for r in reqs
        if Requirement(r).name == "mcp" and "extra == \"mcp\"" in r.replace("'", '"')
    ]
    assert mcp_specs, "google-adk no longer declares an `mcp` extra; revisit the dependency"
    assert _installed("mcp"), (
        "`mcp` is not installed: `google-adk[mcp]` in pyproject is what brings it, "
        "and `axonflow_mcp_toolset` cannot work without it"
    )
    installed = Version(importlib.metadata.version("mcp"))
    for spec in mcp_specs:
        assert spec.specifier.contains(installed, prereleases=True), (
            f"installed mcp {installed} is outside google-adk's declared {spec.specifier}"
        )


def test_this_package_asks_google_adk_for_its_mcp_extra() -> None:
    # Guards the pyproject line itself, through the installed metadata rather
    # than a TOML parse, so it reads what pip would. Dropping the extra puts
    # every fresh install back where the v1.2.0 release run found it.
    if not _installed("axonflow-google-adk-plugin"):
        pytest.skip("plugin is not pip-installed; metadata unavailable")
    from packaging.requirements import Requirement

    adk = [
        Requirement(r)
        for r in importlib.metadata.requires("axonflow-google-adk-plugin") or []
        if Requirement(r).name == "google-adk"
    ]
    assert adk, "pyproject no longer depends on google-adk"
    assert any("mcp" in r.extras for r in adk), (
        "pyproject must depend on `google-adk[mcp]`, not bare `google-adk`"
    )
