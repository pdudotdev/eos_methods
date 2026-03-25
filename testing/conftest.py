"""
Shared fixtures for the arista.py test suite.

Adds the project root to sys.path so `import arista` works,
and provides reusable test data for unit and integration tests.
The --live flag is registered here (root conftest) so pytest
recognises it before collecting subdirectories.
"""
import sys
from pathlib import Path

# arista.py is a standalone script, not a package — put its directory on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from arista import ConnectionResult


# ── CLI flag: --live (must live in root conftest) ───────────────

def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", default=False, help="run live device tests")


def pytest_collection_modifyitems(config, items):
    """Skip tests marked @pytest.mark.live unless --live is passed."""
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="need --live flag to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def sample_params():
    """Minimal SWITCH_PARAMS-shaped dict for tests that never hit the network."""
    return {
        "host": "10.0.0.1",
        "username": "admin",
        "password": "admin",
        "eapi_port": 443,
        "restconf_port": 6020,
        "netconf_port": 830,
        "gnmi_port": 6030,
        "ssh_port": 22,
        "telnet_port": 23,
        "verify_ssl": False,
        "gnmi_cert": "/tmp/fake.crt",
    }


@pytest.fixture
def sample_oc_ifaces():
    """Three OpenConfig-style interface dicts for testing _oc_ifaces_summary."""
    return [
        {
            "name": "Ethernet1",
            "config": {"description": "TO-SPINE1"},
            "state": {"admin-status": "UP", "oper-status": "UP"},
        },
        {
            "name": "Ethernet2",
            "config": {"description": "TO-SPINE2"},
            "state": {"admin-status": "UP", "oper-status": "DOWN"},
        },
        {
            "name": "Management0",
            "config": {"description": "OOB"},
            "state": {"admin-status": "UP", "oper-status": "UP"},
        },
    ]


@pytest.fixture
def sample_netconf_xml():
    """Valid NETCONF XML response with two interfaces under the OpenConfig namespace."""
    return (
        '<data xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">'
        '<interfaces xmlns="http://openconfig.net/yang/interfaces">'
        "<interface>"
        "<name>Ethernet1</name>"
        "<config><description>TO-SPINE1</description></config>"
        "<state><admin-status>UP</admin-status><oper-status>UP</oper-status></state>"
        "</interface>"
        "<interface>"
        "<name>Management0</name>"
        "<config><description></description></config>"
        "<state><admin-status>UP</admin-status><oper-status>UP</oper-status></state>"
        "</interface>"
        "</interfaces>"
        "</data>"
    )


@pytest.fixture
def make_result():
    """Factory fixture — creates a ConnectionResult with customizable fields."""
    def _make(**kwargs):
        defaults = {
            "method": "TestMethod",
            "success": True,
            "elapsed_seconds": 1.0,
            "data": None,
            "error": None,
            "raw_output": "test output",
        }
        defaults.update(kwargs)
        return ConnectionResult(**defaults)
    return _make
