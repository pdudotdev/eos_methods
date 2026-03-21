# Arista Management API Ports

| Method | Wireshark Filter |
|---|---|
| SSH/CLI | `tcp.port == 22` |
| eAPI | `tcp.port == 443` |
| RESTCONF | `tcp.port == 6020` |
| NETCONF | `tcp.port == 830` |
| gNMI | `tcp.port == 6030` |
| Telnet/CLI | `tcp.port == 23` |