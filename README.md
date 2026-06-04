# Aimili Node CLI

Terminal helper for managing AimiliVPN/VPNGate nodes on a VPS over SSH.

It can list nodes, test nodes, connect to a node, save good nodes, and switch between saved nodes even after Aimili refreshes its node list.

## Requirements

- A VPS with AimiliVPN installed.
- SSH access from your local machine to the VPS.
- Python 3 on both local machine and VPS.
- `requests` available on the VPS Python environment.
- AimiliVPN auth data available on the VPS at:

```text
/opt/aimilivpn/vpngate_data/ui_auth.json
```

The script does not store your Aimili panel password locally. It reads Aimili auth from the VPS-side `ui_auth.json` through SSH.

## Quick Start

Run a command by passing your VPS host:

```bash
python3 aimili_node_cli.py --host <vps-host> status
```

Or set an environment variable:

```bash
export AIMILI_HOST=<vps-host>
python3 aimili_node_cli.py status
```

The SSH user defaults to `root`. Use `--ssh-user` if needed:

```bash
python3 aimili_node_cli.py --host <vps-host> --ssh-user ubuntu status
```

## Check Current Exit IP

```bash
python3 aimili_node_cli.py --host <vps-host> status
```

Look for:

```text
current proxy ip:
219.100.37.233

active node:
1. * JP_219.100.37.5_443_tcp
```

`current proxy ip` is the real exit IP of the Aimili socks5 proxy running on the VPS.

## Find US Nodes

List US nodes:

```bash
python3 aimili_node_cli.py --host <vps-host> list --country US
```

List US residential/normal-quality candidates:

```bash
python3 aimili_node_cli.py --host <vps-host> list --country US --residential
```

List available US nodes:

```bash
python3 aimili_node_cli.py --host <vps-host> list --country US --available
```

Refresh nodes and save good US residential/normal candidates:

```bash
python3 aimili_node_cli.py --host <vps-host> refresh --country US --residential --save-good
```

## Test Before Switching

Always test a node before switching:

```bash
python3 aimili_node_cli.py --host <vps-host> test US_76.14.40.202_1743_tcp
```

If the response contains:

```text
"ok": true
```

the node is currently connectable.

## Save Nodes

Save the active node:

```bash
python3 aimili_node_cli.py --host <vps-host> save-active --alias current
```

Save a specific node:

```bash
python3 aimili_node_cli.py --host <vps-host> save US_76.14.40.202_1743_tcp --alias us1
```

Save good nodes from the current list:

```bash
python3 aimili_node_cli.py --host <vps-host> save-good --country US --residential
```

Saved nodes include the OpenVPN `config_text`, not just the node ID. This helps preserve old good nodes after Aimili refreshes or cleans temporary `.ovpn` files.

## View Saved Nodes

```bash
python3 aimili_node_cli.py --host <vps-host> favorites
```

Example:

```text
1. US_38.13.25.52_1356_udp alias=starry38
   美国 | quality=normal | type=residential | status=unavailable

2. JP_219.100.37.5_443_tcp alias=current
   日本 | quality=proxy | type=proxy | status=available
```

`available` means the node is currently connectable. `unavailable` means the script kept the node record and config, but the remote node cannot currently be reached.

## Switch Nodes

Switch by alias:

```bash
python3 aimili_node_cli.py --host <vps-host> connect-saved current
```

Or:

```bash
python3 aimili_node_cli.py --host <vps-host> connect-saved starry38
```

Switch by full node ID:

```bash
python3 aimili_node_cli.py --host <vps-host> connect-saved US_38.13.25.52_1356_udp
```

If a switch fails, reconnect to a known-good saved node:

```bash
python3 aimili_node_cli.py --host <vps-host> connect-saved current
```

## Recommended Workflow

Find and save new US residential candidates:

```bash
python3 aimili_node_cli.py --host <vps-host> refresh --country US --residential --save-good
python3 aimili_node_cli.py --host <vps-host> favorites
```

Test and switch:

```bash
python3 aimili_node_cli.py --host <vps-host> test <node-id>
python3 aimili_node_cli.py --host <vps-host> connect-saved <node-id>
python3 aimili_node_cli.py --host <vps-host> status
```

Save a currently good node:

```bash
python3 aimili_node_cli.py --host <vps-host> save-active --alias current
```

## Notes

- VPNGate nodes are public volunteer nodes. They can go offline, change exit IP, or slow down at any time.
- A saved node with `status=unavailable` is preserved for retrying later, but it is not currently usable.
- Google's displayed region may come from account settings, cookies, or browser location permissions. Check the real exit IP with `status` and an IP database such as `ipinfo.io`.
- Aimili may rewrite or delete temporary `.ovpn` files during connection. This tool preserves complete `config_text` for saved nodes.

## License

MIT
