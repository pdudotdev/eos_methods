# EOS Methods - Weekend Fun Experiment

## 📖 **Table of Contents**
- [📄 Summary](#-summary)
- [📋 Steps](#-steps)
- [📍 Final Report](#-final-report)
- [⚠️ Disclaimer](#️-disclaimer)

## 📄 Summary
Testing CLI/SSH, NETCONF, RESTCONF, gNMI, eAPI (and Telnet 😝) on Arista EOS.

Luckily, Arista provides us with the chance to download and test its OS [**for free**](https://www.arista.com/en/login), and on top of that EOS supports 5 data retrieval methods (*+ Telnet, just for fun*) necessary for network automation:

| Method | Port | Transport | Data Format | Security |                                                                                                                                                                         
  |---|---|---|---|---|                                                                                                                                                                                                        
  | eAPI | 443 | HTTP/1.1 over TLS 1.3 | JSON-RPC — native EOS schema | Encrypted (TLS 1.3) |                                                                                                                                    
  | RESTCONF | 6020 | HTTP/1.1 over TLS 1.3 | JSON — YANG / OpenConfig | Encrypted (TLS 1.3) |                                                                                                                                   
  | gNMI | 6030 | gRPC over HTTP/2 over TLS 1.3 | Protobuf / JSON — YANG / OpenConfig | Encrypted (TLS 1.3) |                                                                                                                    
  | NETCONF | 830 | SSHv2 subsystem | XML — YANG / OpenConfig | Encrypted (SSHv2) |                                                                                                                                              
  | SSH/CLI | 22 | SSHv2 | Plain text — CLI output | Encrypted (SSHv2) |                                                                                                                                                         
  | Telnet/CLI | 23 | Telnet | Plain text — CLI output | **None — plaintext** |

## 📋 Steps
- Have an Arista EOS device up and reachable
- See all the necessary EOS configs [**here**](eos_setup/eos_setup.txt)
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
  Arista Switch -- 6-Method Concurrent Benchmark
  Target: 172.20.20.208
  Query : show interfaces status
============================================================

  Starting all 6 connections simultaneously...
  Methods: SSH/CLI | eAPI | RESTCONF | NETCONF | gNMI | Telnet

  All connections completed in 6.7608s (wall clock)

  Rank   Method                         Time (s)     Status
  ------------------------------------------------------------
  1      eAPI (HTTPS JSON-RPC)          0.0970       OK
  2      RESTCONF (HTTPS REST)          0.1100       OK
  3      gNMI (pygnmi/gRPC)             0.2340       OK
  4      SSH/CLI (Netmiko)              1.9670       OK
  5      NETCONF (ncclient)             2.2400       OK
  6      Telnet/CLI (Netmiko)           6.4440       OK

  Full report written to: notes/arista_benchmark_results.txt
```
- Run `RUNS = 500` tests, get the average: `python benchmark_runner.py`
```
  Completed 500 runs

  Rank   Method                         Avg Time (s)   Success Rate
  -----------------------------------------------------------------
  1      eAPI (HTTPS JSON-RPC)          0.0990         500/500
  2      RESTCONF (HTTPS REST)          0.1178         500/500
  3      gNMI (pygnmi/gRPC)             0.2641         500/500
  4      SSH/CLI (Netmiko)              1.9690         500/500
  5      NETCONF (ncclient)             2.3410         500/500
  6      Telnet/CLI (Netmiko)           6.4105         500/500

```
- Query outputs are saved to `notes/arista_benchmark_results.txt`
- You can also run **Wireshark** to see more details (*GEEK!*)
  - [x] Use the filters provided [**here**](https://github.com/pdudotdev/eos_methods/blob/main/notes/notes.md)
  - [x] Or check out the PCAPs in `pcaps/`

**Have fun! 🤓**

## 📍 Final Report
- See the full [**REPORT.md**](REPORT.md)
- ... or just [**REPORT_TLDR.md**](REPORT_TLDR.md)

## ⚠️ Disclaimer
**Lab context:** Results are from an Arista **cEOS 4.35.0F** lab in **containerlab**, client and device on the same local subnet. Rankings and absolute times may differ on physical EOS hardware (which supports gNMI `encoding="proto"`, reducing gNMI's response size significantly), over WAN or high-latency links, with TACACS+/RADIUS authentication (adds network RTT to every SSH/NETCONF connection), on different EOS versions, or with other vendors.

Educational purposes only. License MIT.