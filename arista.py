#!/usr/bin/env python3
"""
Arista Switch - 5-Method Concurrent Connection Benchmark
=========================================================
Connects to an Arista EOS switch simultaneously via:
  1. SSH/CLI   (using Netmiko)
  2. eAPI      (using requests - HTTPS JSON-RPC)
  3. RESTCONF  (using requests - HTTPS REST)
  4. NETCONF   (using ncclient)
  5. gNMI      (using pygnmi)

All methods query for interface status information.
SSH and eAPI use "show interfaces status" directly.
RESTCONF, NETCONF, and gNMI use the equivalent OpenConfig path:
  /openconfig-interfaces:interfaces

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
from dataclasses import dataclass
from typing import Any, Optional

warnings.filterwarnings("ignore")

import os
import logging
logging.getLogger("pygnmi").setLevel(logging.CRITICAL)
os.environ["GRPC_VERBOSITY"] = "NONE"
os.environ["GRPC_TRACE"] = ""

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
    "verify_ssl": False,
}

OUTPUT_FILE = "notes/arista_benchmark_results.txt"


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
            "password": params["password"],
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
            verify=params["verify_ssl"], timeout=30,
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
            verify=params["verify_ssl"], timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        result.success = True
        result.data = data
        result.raw_output = json.dumps(data, indent=2)
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
            password=params["password"],
            hostkey_verify=False,
            device_params={"name": "default"},
            timeout=30,
        ) as m:
            response = m.get(filter=("subtree", iface_filter))
            output = response.xml
        result.success = True
        result.raw_output = output
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
        with gNMIclient(
            target=(params["host"], params["gnmi_port"]),
            username=params["username"],
            password=params["password"],
            insecure=False,
            skip_verify=True,
        ) as gc:
            gnmi_result = gc.get(
                path=["/interfaces"],
                encoding="json",
            )
        result.success = True
        result.data = gnmi_result
        result.raw_output = json.dumps(gnmi_result, indent=2, default=str)
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        result.elapsed_seconds = time.perf_counter() - start
    return result


# ──────────────────────────────────────────────
# 6. Telnet / CLI  (Netmiko)
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
# Orchestrator — run all 6 concurrently
# ──────────────────────────────────────────────
def run_benchmark(params: dict) -> list[ConnectionResult]:
    methods = [
        connect_ssh_cli,
        connect_eapi,
        connect_restconf,
        connect_netconf,
        connect_gnmi,
        connect_telnet,
    ]
    results: list[ConnectionResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
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
        "ARISTA SWITCH - 5-METHOD CONNECTION BENCHMARK".center(w),
        sep,
        f"  Target Host  : {params['host']}",
        f"  Timestamp    : {timestamp}",
        f"  Query        : show interfaces status / openconfig-interfaces:interfaces",
        f"  Methods      : SSH/CLI, eAPI, RESTCONF, NETCONF, gNMI",
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
    print("  Arista Switch -- 5-Method Concurrent Benchmark")
    print(f"  Target: {SWITCH_PARAMS['host']}")
    print(f"  Query : show interfaces status")
    print(f"{'=' * 60}\n")
    print("  Starting all 5 connections simultaneously...")
    print("  Methods: SSH/CLI | eAPI | RESTCONF | NETCONF | gNMI | Telnet\n")

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
