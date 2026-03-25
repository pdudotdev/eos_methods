"""
Live device tests — connect to a real Arista switch (172.20.20.208) via each
of the 6 methods and verify real data comes back.

Run with:  pytest testing/ --live -v

Each test appends its ConnectionResult to the shared live_results list,
which the conftest's write_live_md fixture uses to generate testing/live.md.
"""
import pytest
from arista import (
    connect_ssh_cli,
    connect_eapi,
    connect_restconf,
    connect_netconf,
    connect_gnmi,
    connect_telnet,
)


@pytest.mark.live
def test_ssh_cli(switch_params, live_results):
    """SSH is the most common management protocol. Connect via Netmiko with
    device_type arista_eos, run 'show interfaces status', and verify we get
    real interface names back in the output."""
    result = connect_ssh_cli(switch_params)
    live_results.append(result)

    assert result.success is True, f"SSH failed: {result.error}"
    assert result.elapsed_seconds > 0
    # Arista interface names start with "Et" (Ethernet) or "Ma" (Management)
    assert "Et" in result.raw_output or "Ma" in result.raw_output


@pytest.mark.live
def test_eapi(switch_params, live_results):
    """eAPI is Arista's native HTTPS JSON-RPC interface. Verify we get a valid
    JSON response containing interfaceStatuses — the key returned by
    'show interfaces status' in JSON format."""
    result = connect_eapi(switch_params)
    live_results.append(result)

    assert result.success is True, f"eAPI failed: {result.error}"
    assert isinstance(result.data, dict)
    assert "interfaceStatuses" in result.data


@pytest.mark.live
def test_restconf(switch_params, live_results):
    """RESTCONF queries the OpenConfig /interfaces path over HTTPS REST.
    The raw_output is rendered by _oc_ifaces_summary, so we check for
    the table header as proof that data was parsed successfully."""
    result = connect_restconf(switch_params)
    live_results.append(result)

    assert result.success is True, f"RESTCONF failed: {result.error}"
    assert "Interface" in result.raw_output


@pytest.mark.live
def test_netconf(switch_params, live_results):
    """NETCONF uses ncclient over SSH (port 830) with an OpenConfig subtree filter.
    The XML response is parsed by _netconf_xml_summary into an ASCII table.
    Verify the table header appears, confirming successful XML parsing."""
    result = connect_netconf(switch_params)
    live_results.append(result)

    assert result.success is True, f"NETCONF failed: {result.error}"
    assert "Interface" in result.raw_output


@pytest.mark.live
def test_gnmi(switch_params, live_results):
    """gNMI uses gRPC over HTTP/2 with a pinned TLS certificate. The response
    is a notification structure containing interface data. Verify the top-level
    'notification' key exists in the parsed response."""
    result = connect_gnmi(switch_params)
    live_results.append(result)

    assert result.success is True, f"gNMI failed: {result.error}"
    assert result.data is not None
    assert "notification" in result.data


@pytest.mark.live
def test_telnet(switch_params, live_results):
    """Telnet is the legacy unencrypted CLI protocol. Connect via Netmiko with
    device_type arista_eos_telnet and verify interface names appear in the
    'show interfaces status' output."""
    result = connect_telnet(switch_params)
    live_results.append(result)

    assert result.success is True, f"Telnet failed: {result.error}"
    assert "Et" in result.raw_output or "Ma" in result.raw_output
