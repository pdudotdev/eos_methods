"""Live device tests — connect to a real Arista switch via each protocol.

Run with:  pytest testing/ --live -v
"""
import pytest
from arista import (
    connect_ssh_cli,
    connect_eapi,
    connect_restconf,
    connect_netconf,
    connect_gnmi,
    connect_snmpv3,
    connect_telnet,
)


@pytest.mark.live
@pytest.mark.parametrize("connect_fn, check", [
    pytest.param(connect_ssh_cli,  lambda r: "Ethernet" in r.raw_output or "Management" in r.raw_output, id="ssh"),
    pytest.param(connect_eapi,     lambda r: isinstance(r.data, dict) and "interfaceStatuses" in r.data, id="eapi"),
    pytest.param(connect_restconf, lambda r: "Interface" in r.raw_output, id="restconf"),
    pytest.param(connect_netconf,  lambda r: "Interface" in r.raw_output, id="netconf"),
    pytest.param(connect_gnmi,     lambda r: r.data is not None and "notification" in r.data, id="gnmi"),
    pytest.param(connect_snmpv3,   lambda r: "Interface" in r.raw_output or "Ethernet" in r.raw_output, id="snmpv3"),
    pytest.param(connect_telnet,   lambda r: "Ethernet" in r.raw_output or "Management" in r.raw_output, id="telnet"),
])
def test_live_connection(switch_params, live_results, connect_fn, check):
    result = connect_fn(switch_params)
    live_results.append(result)
    assert result.success is True, f"{connect_fn.__name__} failed: {result.error}"
    assert result.elapsed_seconds > 0
    assert check(result), f"Protocol-specific check failed for {connect_fn.__name__}"
