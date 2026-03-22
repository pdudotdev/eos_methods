Who's faster, and why? CLI-SSH v. NETCONF v. RESTCONF v. gNMI v. eAPI

I had some fun this weekend with an Arista EOS in containerlab.
Had the urge to get my hands dirty with some Wireshark, too.
You'll find the full final writeup, PCAPs, and repo below.

Withouth further ado...

Spoiler alert! After 100 tests, the avg. results are:
  1. eAPI (HTTPS JSON-RPC): 0.0990s
  2. RESTCONF (HTTPS REST): 0.1178s
  3. gNMI (pygnmi/gRPC): 0.2641s
  4. SSH/CLI (Netmiko): 1.9690s
  5. NETCONF (ncclient): 2.3810s
  6. Telnet/CLI (Netmiko): 6.4105s

But why? Time to get our hands dirty.

⏱️ Timing Breakdown

▫️ eAPI (JSON-RPC):
TCP handshake: ~0.05ms
Python SSL context setup: ~52.8ms
TLS 1.3 handshake: ~4.3ms
HTTP request transmission: ~0.3ms
Server processing: ~32ms
HTTP response: ~6.8ms
TCP teardown: ~0.8ms
➜ TOTAL PACKETS: 19
➜ TOTAL TIME: ~97ms

▫️ RESTCONF:
TCP handshake: ~0.04ms
Python SSL context setup: ~44.7ms
TLS 1.3 handshake: ~5ms
HTTP GET request: ~1ms
Server processing (YANG translation): ~56ms
HTTP response (23KB, 8 segments): ~1ms
Connection close: ~1ms
➜ TOTAL PACKETS: 25
➜ TOTAL: ~110ms

▫️ gNMI:
Connection 1 — certificate retrieval (TCP + TLS + RST): ~15ms
Gap — pygnmi builds gRPC credentials from extracted cert: ~21ms
TCP handshake (connection 2): ~0.04ms
TLS 1.3 handshake: ~23ms
HTTP/2 + gRPC setup (SETTINGS, HEADERS): ~5ms
Server processing — initial (YANG + protobuf): ~74ms
gNMI response burst 1 (17KB): ~2ms
Server processing — continued: ~41ms
gNMI response burst 2 (24KB) + delayed ACK: ~41ms
HTTP/2 GOAWAY + TCP teardown: ~25ms
➜ TOTAL PACKETS: 50
➜ TOTAL: ~263ms

▫️ SSH/CLI:
TCP handshake: ~0.05ms
SSH banner exchange: ~27ms
SSH key exchange: ~47ms
Encrypted authentication: ~1,540ms (incl. 1,476ms password auth gap)
Channel setup + Netmiko prep: ~197ms
Command + response: ~153ms
➜ TOTAL PACKETS: 80
➜ TOTAL: ~1967ms

▫️ NETCONF:
TCP handshake: ~0.07ms
SSH banner exchange: ~28ms
SSH key exchange: ~90ms
SSH authentication: ~56ms
Password auth (server-side): ~1,474ms
SSH channel + NETCONF hello: ~52ms
Server processing (YANG + XML): ~187ms
XML response (156KB, 845 segments): ~215ms
Session teardown: ~137ms
➜ TOTAL PACKETS: 1130
➜ TOTAL: ~2240ms

▫️ Telnet:
TCP handshake: ~0.05ms
Server IAC round 1: ~9ms
Netmiko sleep: ~992ms
Client WONT responses: ~1ms
Server IAC round 2: ~1ms
Netmiko sleep: ~501ms
IAC exchanges + Username prompt: ~42ms
Netmiko sleep: ~460ms
Username entry: ~42ms
Password prompt + Netmiko sleep: ~951ms
Password entry: ~1ms
Server auth + banner + prompt: ~1,516ms
Netmiko session prep + sleep: ~1,795ms
Command + response: ~110ms
TCP teardown: ~0.3ms
➜ TOTAL PACKETS: 95
➜ TOTAL: ~6444ms