# EOS Methods - Weekend Fun Experiment

## 📖 **Table of Contents**
- [📄 Summary](#-summary)
- [📋 Steps](#-steps)
- [📍 Final Report](#-final-report)
- [⚠️ Disclaimer](#️-disclaimer)

## 📄 Summary
Testing CLI/SSH, NETCONF, RESTCONF, gNMI, eAPI, SNMPv3 (and Telnet 😝) on Arista EOS.

Luckily, Arista provides us with the chance to download and test its OS [**for free**](https://www.arista.com/en/login), and on top of that EOS supports 6 data retrieval methods (*+ Telnet, just for fun*) necessary for network automation:

| Method | Port | Transport | Data Format | Security |                                                                                                                                                                         
  |---|---|---|---|---|                                                                                                                                                                                                        
  | eAPI | 443 | HTTP/1.1 over TLS 1.3 | JSON-RPC — native EOS schema | Encrypted (TLS 1.3) |                                                                                                                                    
  | RESTCONF | 6020 | HTTP/1.1 over TLS 1.3 | JSON — YANG / OpenConfig | Encrypted (TLS 1.3) |                                                                                                                                   
  | gNMI | 6030 | gRPC over HTTP/2 over TLS 1.3 | Protobuf / JSON — YANG / OpenConfig | Encrypted (TLS 1.3) |                                                                                                                    
  | SNMPv3 | 161 | UDP | SNMP PDU — IF-MIB | Encrypted (USM: SHA auth + AES-128 priv) |
  | NETCONF | 830 | SSHv2 subsystem | XML — YANG / OpenConfig | Encrypted (SSHv2) |                                                                                                                                              
  | SSH/CLI | 22 | SSHv2 | Plain text — CLI output | Encrypted (SSHv2) |                                                                                                                                                         
  | Telnet/CLI | 23 | Telnet | Plain text — CLI output | **None — plaintext** |

## 📋 Steps
- Have an Arista EOS device up and reachable
- See all the necessary EOS configs [**here**](eos_setup/commands.txt)
- Create a venv: 
```
python3 -m venv arista
source arista/bin/activate
```
- Install requirements:
```
pip install -r requirements.txt
```
- Set your device's **mgmt IP and credentials** in `arista.py`
- Run the test once: `python arista.py`
```
============================================================
  Arista Switch -- 7-Method Concurrent Benchmark
  Target: 172.20.20.208
  Query : show interfaces status
============================================================

  Starting all 7 connections simultaneously...
  Methods: SSH/CLI | eAPI | RESTCONF | NETCONF | gNMI | SNMPv3 | Telnet


  All connections completed in 7.4372s (wall clock)

  Rank   Method                         Time (s)     Status
  ------------------------------------------------------------
  1      eAPI (HTTPS JSON-RPC)          0.0700       OK
  2      RESTCONF (HTTPS REST)          0.1233       OK
  3      gNMI (pygnmi/gRPC)             0.2282       OK
  4      SNMPv3 (pysnmp/USM)            0.4341       OK
  5      SSH/CLI (Netmiko)              1.9084       OK
  6      NETCONF (ncclient)             2.7243       OK
  7      Telnet/CLI (Netmiko)           6.4154       OK

  Full report written to: notes/arista_benchmark_results.txt
```
- Run `RUNS = 100` tests, get the average: `python benchmark_runner.py`
- Query outputs are saved to `notes/arista_benchmark_results.txt`
- You can also run **Wireshark** to see more details (*GEEK!*)
  - [x] Use the filters provided [**here**](https://github.com/pdudotdev/eos_methods/blob/main/notes/notes.md)
  - [x] Or check out the PCAPs in `pcaps/`

**Have fun! 🤓**

## 📍 Final Report
- See the [**REPORT.md**](REPORT.md)

## ⚠️ Disclaimer
**Lab context:** Results are from an Arista **cEOS 4.35.0F** lab in **containerlab**, client and device on the same local subnet. Rankings and absolute times may differ on physical EOS hardware (which supports gNMI `encoding="proto"`, reducing gNMI's response size significantly), over WAN or high-latency links, with TACACS+/RADIUS authentication (adds network RTT to every SSH/NETCONF connection), on different EOS versions, or with other vendors.

Educational purposes only. License MIT.