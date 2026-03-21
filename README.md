# EOS Methods - Weekend Fun Experiment

## Summary
Testing CLI/SSH, NETCONF, RESTCONF, gNMI, eAPI (and Telnet 😝) on Arista EOS.

Luckily, Arista provides us with the chance to download and test is OS [**for free**](https://www.arista.com/en/login), and on top of that EOS supports 5 data retrieval methods necessary for network automation purposes:
- CLI/SSH
- RESTCONF
- NETCONF
- gNMI
- eAPI
- Telnet (just for fun)

## Steps
- Have an Arista EOS device up and reachable
- See all the necessary configuration [**here](eos_setup/eos_setup.txt)
- Create venv: `python3 -m venv arista && source arista\bin\activate`
- Install requirements: `pip install -r requirements.txt`
- Set your device's **mgmt IP and credentials** in the code
- Run the test once: `python arista_multi_connect.py`
```
(arista) mcp@mcp:~/arista$ python arista.py 

============================================================
  Arista Switch -- 5-Method Concurrent Benchmark
  Target: 172.20.20.208
  Query : show interfaces status
============================================================

  Starting all 5 connections simultaneously...
  Methods: SSH/CLI | eAPI | RESTCONF | NETCONF | gNMI


  All connections completed in 6.7608s (wall clock)

  Rank   Method                         Time (s)     Status
  ------------------------------------------------------------
  1      eAPI (HTTPS JSON-RPC)          0.0990       OK
  2      RESTCONF (HTTPS REST)          0.1228       OK
  3      gNMI (pygnmi/gRPC)             0.2454       OK
  4      SSH/CLI (Netmiko)              1.9482       OK
  5      NETCONF (ncclient)             2.3284       OK
  6      Telnet/CLI (Netmiko)           6.3079       OK

  Full report written to: arista_benchmark_results.txt
```
- Run 100 tests, get the average: `python benchmark_runner.py`
```
  Completed 100 runs

  Rank   Method                         Avg Time (s)   Success Rate
  -----------------------------------------------------------------
  1      eAPI (HTTPS JSON-RPC)          0.0965         100/100
  2      RESTCONF (HTTPS REST)          0.1256         100/100
  3      gNMI (pygnmi/gRPC)             0.2479         100/100
  4      SSH/CLI (Netmiko)              1.9713         100/100
  5      NETCONF (ncclient)             2.3871         100/100
  6      Telnet/CLI (Netmiko)           6.4224         100/100

```
- Output of each query is saved to `arista_benchmark_results.txt`
- Findings and lessons learned, saved to `findings/findings.md`
- You can also run **Wireshark** to see more details (GEEK!)

**Have fun! 🤓**

## Disclaimer
Educational purposes only. License MIT.