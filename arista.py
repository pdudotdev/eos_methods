#!/usr/bin/env python3
"""
Arista Switch - 7-Method Concurrent Connection Benchmark
=========================================================
Connects to an Arista EOS switch simultaneously via:
  1. SSH/CLI   (using Netmiko)
  2. eAPI      (using requests - HTTPS JSON-RPC)
  3. RESTCONF  (using requests - HTTPS REST)
  4. NETCONF   (using ncclient)
  5. gNMI      (using pygnmi)
  6. SNMPv3    (using pysnmp - USM authPriv)
  7. Telnet    (using Netmiko)

All methods query for interface status information.
SSH, eAPI, and Telnet use "show interfaces status" directly.
RESTCONF, NETCONF, and gNMI use the equivalent OpenConfig path:
  /openconfig-interfaces:interfaces
SNMPv3 walks IF-MIB::ifTable for interface name, admin, and oper status.

Prerequisites
-------------
pip install -r requirements.txt

Usage
-----
  python arista.py

Edit the SWITCH_PARAMS dict below with your device details.
"""

import json
import time
import datetime
import concurrent.futures
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Optional

warnings.filterwarnings("ignore")

import os
import logging
logging.getLogger("pygnmi").setLevel(logging.CRITICAL)
os.environ["GRPC_VERBOSITY"] = "NONE"
os.environ["GRPC_TRACE"] = ""
os.environ.setdefault("SSLKEYLOGFILE", "pcaps/tls_keys.log")

# ──────────────────────────────────────────────
# CONFIGURATION — Edit these to match your switch
# ──────────────────────────────────────────────
SWITCH_PARAMS = {
    "host": "172.20.20.208",
    "username": "admin",
    "password": "admin",
    "eapi_port": 443,
    "restconf_port": 6020,
    "netconf_port": 830,
    "gnmi_port": 6030,
    "ssh_port": 22,
    "telnet_port": 23,
    "ssh_key": "secrets_example/ssh_key",
    "ca_cert": "secrets_example/ca.crt",
    "client_cert": "secrets_example/client.crt",
    "client_key": "secrets_example/client.key",
    "snmpv3_user": "benchmark",
    "snmpv3_auth_key": "admin1234",
    "snmpv3_priv_key": "admin1234",
    "snmpv3_port": 161,
}

OUTPUT_FILE = "notes/arista_benchmark_results.txt"


def _oc_ifaces_summary(ifaces: list) -> str:
    """Render an OpenConfig interface list as a compact status table."""
    if not ifaces:
        return "(no interface data)"
    rows = [f"{'Interface':<20} {'Description':<22} {'Admin':<8} {'Oper'}", "-" * 62]
    for iface in ifaces:
        name  = iface.get("name") or (iface.get("config") or {}).get("name", "?")
        desc  = ((iface.get("config") or {}).get("description", "") or "")[:22]
        state = iface.get("state") or {}
        admin = state.get("admin-status", "?")
        oper  = state.get("oper-status", "?")
        rows.append(f"{name:<20} {desc:<22} {admin:<8} {oper}")
    return "\n".join(rows)


def _netconf_xml_summary(xml_str: str) -> str:
    """Extract interface status table from a NETCONF XML rpc-reply."""
    try:
        root = ET.fromstring(xml_str)
        ns = "http://openconfig.net/yang/interfaces"
        ifaces = []
        for iface in root.iter(f"{{{ns}}}interface"):
            name  = iface.findtext(f"{{{ns}}}name", "?")
            desc  = iface.findtext(f"{{{ns}}}config/{{{ns}}}description", "") or ""
            admin = iface.findtext(f"{{{ns}}}state/{{{ns}}}admin-status", "?")
            oper  = iface.findtext(f"{{{ns}}}state/{{{ns}}}oper-status", "?")
            ifaces.append({"name": name, "config": {"description": desc},
                           "state": {"admin-status": admin, "oper-status": oper}})
        return _oc_ifaces_summary(ifaces)
    except Exception as exc:
        return f"(XML parse error: {exc})\n{xml_str[:500]}"


@dataclass
class ConnectionResult:
    method: str
    success: bool = False
    elapsed_seconds: float = 0.0
    data: Any = None
    error: Optional[str] = None
    raw_output: str = ""


# ──────────────────────────────────────────────
# 1. SSH / CLI  (Netmiko)
# ──────────────────────────────────────────────
def connect_ssh_cli(params: dict) -> ConnectionResult:
    from netmiko import ConnectHandler
    result = ConnectionResult(method="SSH/CLI (Netmiko)")
    start = time.perf_counter()
    try:
        device = {
            "device_type": "arista_eos",
            "host": params["host"],
            "username": params["username"],
            "use_keys": True,
            "key_file": params["ssh_key"],
            "port": params["ssh_port"],
            "timeout": 30,
        }
        conn = ConnectHandler(**device)
        output = conn.send_command("show interfaces status")
        conn.disconnect()
        result.success = True
        result.raw_output = output
        result.data = {"source": "show interfaces status via SSH"}
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        result.elapsed_seconds = time.perf_counter() - start
    return result


# ──────────────────────────────────────────────
# 2. eAPI  (HTTPS JSON-RPC via requests)
# ──────────────────────────────────────────────
def connect_eapi(params: dict) -> ConnectionResult:
    import requests
    from requests.auth import HTTPBasicAuth
    result = ConnectionResult(method="eAPI (HTTPS JSON-RPC)")
    start = time.perf_counter()
    try:
        url = f"https://{params['host']}:{params['eapi_port']}/command-api"
        payload = {
            "jsonrpc": "2.0",
            "method": "runCmds",
            "params": {
                "version": 1,
                "cmds": ["show interfaces status"],
                "format": "json",
            },
            "id": "benchmark-eapi",
        }
        resp = requests.post(
            url, json=payload,
            auth=HTTPBasicAuth(params["username"], params["password"]),
            verify=params["ca_cert"],
            cert=(params["client_cert"], params["client_key"]),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        result.success = True
        result.data = data.get("result", [{}])[0]
        result.raw_output = json.dumps(result.data, indent=2)
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        result.elapsed_seconds = time.perf_counter() - start
    return result


# ──────────────────────────────────────────────
# 3. RESTCONF  (HTTPS REST via requests)
# ──────────────────────────────────────────────
def connect_restconf(params: dict) -> ConnectionResult:
    import requests
    from requests.auth import HTTPBasicAuth
    result = ConnectionResult(method="RESTCONF (HTTPS REST)")
    start = time.perf_counter()
    try:
        url = (
            f"https://{params['host']}:{params['restconf_port']}"
            f"/restconf/data/openconfig-interfaces:interfaces"
        )
        headers = {
            "Accept": "application/yang-data+json",
            "Content-Type": "application/yang-data+json",
        }
        resp = requests.get(
            url, headers=headers,
            auth=HTTPBasicAuth(params["username"], params["password"]),
            verify=params["ca_cert"],
            cert=(params["client_cert"], params["client_key"]),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        result.success = True
        result.data = data
        ifaces = data.get("openconfig-interfaces:interface", [])
        result.raw_output = _oc_ifaces_summary(ifaces)
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        result.elapsed_seconds = time.perf_counter() - start
    return result


# ──────────────────────────────────────────────
# 4. NETCONF  (ncclient)
# ──────────────────────────────────────────────
def connect_netconf(params: dict) -> ConnectionResult:
    from ncclient import manager
    result = ConnectionResult(method="NETCONF (ncclient)")
    start = time.perf_counter()
    try:
        iface_filter = '<interfaces xmlns="http://openconfig.net/yang/interfaces"/>'
        with manager.connect(
            host=params["host"],
            port=params["netconf_port"],
            username=params["username"],
            key_filename=params["ssh_key"],
            hostkey_verify=True,
            device_params={"name": "default"},
            timeout=30,
        ) as m:
            response = m.get(filter=("subtree", iface_filter))
            output = response.xml
        result.success = True
        result.raw_output = _netconf_xml_summary(output)
        result.data = {"source": "NETCONF get (openconfig-interfaces:interfaces)"}
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        result.elapsed_seconds = time.perf_counter() - start
    return result


# ──────────────────────────────────────────────
# 5. gNMI  (pygnmi)
# ──────────────────────────────────────────────
def connect_gnmi(params: dict) -> ConnectionResult:
    from pygnmi.client import gNMIclient
    result = ConnectionResult(method="gNMI (pygnmi/gRPC)")
    start = time.perf_counter()
    try:
        # mTLS: path_root verifies the server cert via CA, path_cert/path_key
        # present the client cert to the server for mutual authentication.
        # encoding="json_ietf" is the standards-compliant OpenConfig encoding
        # (namespace-qualified keys). This EOS version does not support proto
        # encoding; on platforms that do, proto would be significantly smaller.
        # In production, the gNMIclient would be kept alive across queries
        # (persistent channel) to avoid paying TLS + HTTP/2 setup per call.
        with gNMIclient(
            target=(params["host"], params["gnmi_port"]),
            username=params["username"],
            password=params["password"],
            path_root=params["ca_cert"],
            path_cert=params["client_cert"],
            path_key=params["client_key"],
        ) as gc:
            gnmi_result = gc.get(
                path=["/interfaces"],
                encoding="json_ietf",
            )
        result.success = True
        result.data = gnmi_result
        try:
            val = gnmi_result["notification"][0]["update"][0]["val"]
            ifaces = (
                val.get("openconfig-interfaces:interface")
                or val.get("interface", [])
            )
        except (KeyError, IndexError):
            ifaces = []
        result.raw_output = _oc_ifaces_summary(ifaces)
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        result.elapsed_seconds = time.perf_counter() - start
    return result


# ──────────────────────────────────────────────
# 6. SNMPv3  (pysnmp — USM authPriv)
# ──────────────────────────────────────────────
def connect_snmpv3(params: dict) -> ConnectionResult:
    from pysnmp.hlapi.v3arch.asyncio import (
        SnmpEngine, UsmUserData, UdpTransportTarget, ContextData,
        ObjectType, ObjectIdentity, bulk_cmd,
        usmHMACSHAAuthProtocol, usmAesCfb128Protocol,
    )
    import asyncio
    result = ConnectionResult(method="SNMPv3 (pysnmp/USM)")
    start = time.perf_counter()
    try:
        async def _bulk():
            engine = SnmpEngine()
            user = UsmUserData(
                params["snmpv3_user"],
                authKey=params["snmpv3_auth_key"],
                privKey=params["snmpv3_priv_key"],
                authProtocol=usmHMACSHAAuthProtocol,
                privProtocol=usmAesCfb128Protocol,
            )
            target = await UdpTransportTarget.create(
                (params["host"], params["snmpv3_port"]), timeout=10, retries=2,
            )
            # GETBULK walk — pysnmp v7 uses await, not async for
            ifaces = {}
            iftable = "1.3.6.1.2.1.2.2.1"      # IF-MIB::ifTable
            ifalias = "1.3.6.1.2.1.31.1.1.1.18" # IF-MIB::ifAlias (ifXTable)

            async def _walk(prefix, oids):
                """Walk a single table subtree via GETBULK."""
                req = list(oids)
                while True:
                    err_ind, err_st, err_idx, vbs = await bulk_cmd(
                        engine, user, target, ContextData(),
                        0, 25, *req,
                    )
                    if err_ind:
                        raise RuntimeError(str(err_ind))
                    if err_st:
                        raise RuntimeError(f"SNMP error: {err_st.prettyPrint()} at {err_idx}")
                    done = False
                    for oid, val in vbs:
                        oid_str = str(oid)
                        if not oid_str.startswith(prefix):
                            done = True
                            continue
                        yield oid_str, val
                    if done or not vbs:
                        break
                    req = [ObjectType(ObjectIdentity(str(oid))) for oid, _ in vbs[-len(req):]]

            # Walk 1: ifDescr, ifAdminStatus, ifOperStatus
            async for oid_str, val in _walk(iftable, [
                ObjectType(ObjectIdentity(f"{iftable}.2")),   # ifDescr
                ObjectType(ObjectIdentity(f"{iftable}.7")),   # ifAdminStatus
                ObjectType(ObjectIdentity(f"{iftable}.8")),   # ifOperStatus
            ]):
                idx = oid_str.split(".")[-1]
                if f"{iftable}.2." in oid_str:
                    ifaces.setdefault(idx, {})["name"] = str(val)
                elif f"{iftable}.7." in oid_str:
                    ifaces.setdefault(idx, {})["admin"] = "UP" if int(val) == 1 else "DOWN"
                elif f"{iftable}.8." in oid_str:
                    ifaces.setdefault(idx, {})["oper"] = "UP" if int(val) == 1 else "DOWN"

            # Walk 2: ifAlias (user-configured description, from ifXTable)
            async for oid_str, val in _walk(ifalias, [
                ObjectType(ObjectIdentity(ifalias)),
            ]):
                idx = oid_str.split(".")[-1]
                desc = str(val).strip()
                if idx in ifaces and desc:
                    ifaces[idx]["desc"] = desc

            engine.close_dispatcher()
            return ifaces

        ifaces = asyncio.run(_bulk())
        if not ifaces:
            raise RuntimeError("SNMP walk returned no interface data")
        result.success = True
        result.data = {"source": "IF-MIB::ifTable + ifXTable via SNMPv3"}
        rows = [f"{'Interface':<20} {'Description':<22} {'Admin':<8} {'Oper'}", "-" * 62]
        for idx in sorted(ifaces, key=lambda x: int(x)):
            entry = ifaces[idx]
            rows.append(f"{entry.get('name', '?'):<20} {entry.get('desc', ''):<22} {entry.get('admin', '?'):<8} {entry.get('oper', '?')}")
        result.raw_output = "\n".join(rows) if ifaces else "(no interface data)"
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        result.elapsed_seconds = time.perf_counter() - start
    return result


# ──────────────────────────────────────────────
# 7. Telnet / CLI  (Netmiko)
# ──────────────────────────────────────────────
def connect_telnet(params: dict) -> ConnectionResult:
    from netmiko import ConnectHandler
    result = ConnectionResult(method="Telnet/CLI (Netmiko)")
    start = time.perf_counter()
    try:
        device = {
            "device_type": "arista_eos_telnet",
            "host": params["host"],
            "username": params["username"],
            "password": params["password"],
            "port": params["telnet_port"],
            "timeout": 30,
        }
        conn = ConnectHandler(**device)
        output = conn.send_command("show interfaces status")
        conn.disconnect()
        result.success = True
        result.raw_output = output
        result.data = {"source": "show interfaces status via Telnet"}
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        result.elapsed_seconds = time.perf_counter() - start
    return result


# ──────────────────────────────────────────────
# Orchestrator — run all 7 concurrently
# ──────────────────────────────────────────────
def run_benchmark(params: dict) -> list[ConnectionResult]:
    methods = [
        connect_ssh_cli,
        connect_eapi,
        connect_restconf,
        connect_netconf,
        connect_gnmi,
        connect_snmpv3,
        connect_telnet,
    ]
    results: list[ConnectionResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(methods)) as executor:
        future_map = {
            executor.submit(fn, params): fn.__name__ for fn in methods
        }
        for future in concurrent.futures.as_completed(future_map):
            name = future_map[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(
                    ConnectionResult(method=name, success=False, error=f"Thread error: {exc}")
                )
    results.sort(key=lambda r: r.elapsed_seconds)
    return results


# ──────────────────────────────────────────────
# Report generation
# ──────────────────────────────────────────────
def generate_report(results: list[ConnectionResult], params: dict) -> str:
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    w = 80
    sep = "=" * w
    lines = [
        sep,
        "ARISTA SWITCH - 7-METHOD CONNECTION BENCHMARK".center(w),
        sep,
        f"  Target Host  : {params['host']}",
        f"  Timestamp    : {timestamp}",
        f"  Query        : show interfaces status / openconfig-interfaces:interfaces / IF-MIB::ifTable",
        f"  Methods      : SSH/CLI, eAPI, RESTCONF, NETCONF, gNMI, SNMPv3, Telnet",
        sep, "",
        "PERFORMANCE RANKING (fastest -> slowest)",
        "-" * w,
        f"  {'Rank':<6} {'Method':<30} {'Time (s)':<12} {'Status'}",
        "-" * w,
    ]
    for i, r in enumerate(results, 1):
        status = "OK" if r.success else f"FAIL -- {r.error}"
        lines.append(f"  {i:<6} {r.method:<30} {r.elapsed_seconds:<12.4f} {status}")
    lines.append("-" * w)

    successful = [r for r in results if r.success]
    if successful:
        fastest, slowest = successful[0], successful[-1]
        avg = sum(r.elapsed_seconds for r in successful) / len(successful)
        lines.extend([
            "", "SUMMARY", "-" * w,
            f"  Fastest  : {fastest.method}  ({fastest.elapsed_seconds:.4f}s)",
            f"  Slowest  : {slowest.method}  ({slowest.elapsed_seconds:.4f}s)",
            f"  Average  : {avg:.4f}s",
            f"  Spread   : {slowest.elapsed_seconds - fastest.elapsed_seconds:.4f}s",
            f"  Success  : {len(successful)}/{len(results)}",
        ])

    lines.extend(["", sep, "DETAILED OUTPUT PER METHOD", sep])
    for r in results:
        lines.extend([
            "",
            f">>> {r.method}  [{'OK' if r.success else 'FAILED'}]  ({r.elapsed_seconds:.4f}s)",
            "-" * w,
        ])
        if r.error:
            lines.append(f"  ERROR: {r.error}")
        output = r.raw_output or "(no output captured)"
        if len(output) > 2000:
            output = output[:2000] + "\n  ... [truncated] ..."
        lines.append(output)

    lines.append(f"\n{sep}\nEnd of report\n")
    return "\n".join(lines)


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def main():
    print(f"\n{'=' * 60}")
    print("  Arista Switch -- 7-Method Concurrent Benchmark")
    print(f"  Target: {SWITCH_PARAMS['host']}")
    print(f"  Query : show interfaces status")
    print(f"{'=' * 60}\n")
    print("  Starting all 7 connections simultaneously...")
    print("  Methods: SSH/CLI | eAPI | RESTCONF | NETCONF | gNMI | SNMPv3 | Telnet\n")

    overall_start = time.perf_counter()
    results = run_benchmark(SWITCH_PARAMS)
    overall_elapsed = time.perf_counter() - overall_start

    print(f"\n  All connections completed in {overall_elapsed:.4f}s (wall clock)\n")
    print(f"  {'Rank':<6} {'Method':<30} {'Time (s)':<12} {'Status'}")
    print(f"  {'-' * 60}")
    for i, r in enumerate(results, 1):
        status = "OK" if r.success else "FAIL"
        print(f"  {i:<6} {r.method:<30} {r.elapsed_seconds:<12.4f} {status}")

    report = generate_report(results, SWITCH_PARAMS)
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        f.write(report)

    print(f"\n  Full report written to: {OUTPUT_FILE}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Interrupted. Exiting.\n")
