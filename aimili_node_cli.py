#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import argparse
import os
import shlex
import subprocess
import sys


DEFAULT_HOST = os.environ.get("AIMILI_HOST", "")
DEFAULT_SSH_USER = os.environ.get("AIMILI_SSH_USER", "root")


REMOTE_SCRIPT = r'''
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests


DATA_DIR = Path("/opt/aimilivpn/vpngate_data")
AUTH_FILE = DATA_DIR / "ui_auth.json"
NODES_FILE = DATA_DIR / "nodes.json"
CONFIG_DIR = DATA_DIR / "configs"
FAVORITES_FILE = DATA_DIR / "favorite_nodes.json"
FAVORITE_CONFIG_DIR = DATA_DIR / "favorite_configs"
BASE_HOST = "127.0.0.1"


def load_auth():
    data = json.loads(AUTH_FILE.read_text())
    return {
        "username": data["username"],
        "password": data["password"],
        "port": int(data.get("port", 18787)),
        "secret_path": data["secret_path"].strip("/"),
        "proxy_port": int(data.get("proxy_port", 7928)),
    }


def session():
    auth = load_auth()
    base = f"http://{BASE_HOST}:{auth['port']}/{auth['secret_path']}"
    s = requests.Session()
    r = s.post(
        base + "/api/login",
        json={"username": auth["username"], "password": auth["password"]},
        timeout=10,
    )
    r.raise_for_status()
    payload = r.json()
    if not payload.get("ok"):
        raise RuntimeError(f"login failed: {payload}")
    return s, base, auth


def nodes():
    s, base, _ = session()
    r = s.get(base + "/api/nodes", timeout=25)
    r.raise_for_status()
    return r.json().get("nodes", [])


def load_nodes_file():
    if not NODES_FILE.exists():
        return []
    data = json.loads(NODES_FILE.read_text())
    if isinstance(data, list):
        return data
    return data.get("nodes", [])


def save_nodes_file(items):
    tmp = NODES_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2))
    tmp.replace(NODES_FILE)


def load_favorites():
    if not FAVORITES_FILE.exists():
        return {"version": 1, "nodes": {}}
    data = json.loads(FAVORITES_FILE.read_text())
    if isinstance(data, list):
        return {"version": 1, "nodes": {n["id"]: n for n in data if n.get("id")}}
    data.setdefault("version", 1)
    data.setdefault("nodes", {})
    return data


def save_favorites(data):
    FAVORITES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FAVORITES_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(FAVORITES_FILE)


def safe_filename(value):
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)


def archive_config(node):
    node_id = node.get("id")
    if not node_id:
        raise RuntimeError("node has no id")
    FAVORITE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    dest = FAVORITE_CONFIG_DIR / f"{safe_filename(node_id)}.ovpn"
    src_value = node.get("config_file")
    src = Path(src_value) if src_value else None
    config_text = node.get("config_text") or ""
    if src and src.exists():
        shutil.copy2(src, dest)
        if not config_text:
            config_text = dest.read_text(encoding="utf-8", errors="replace")
    elif config_text:
        dest.write_text(config_text, encoding="utf-8")
    elif dest.exists():
        config_text = dest.read_text(encoding="utf-8", errors="replace")
    else:
        raise RuntimeError(f"no config_file/config_text found for {node_id}")
    if config_text:
        node["config_text"] = config_text
    node["favorite_config_file"] = str(dest)
    node["config_file"] = str(CONFIG_DIR / f"{safe_filename(node_id)}.ovpn")
    return node


def find_live_node(node_id):
    api_node = None
    file_node = None
    for node in nodes():
        if node.get("id") == node_id:
            api_node = dict(node)
            break
    for node in load_nodes_file():
        if node.get("id") == node_id:
            file_node = dict(node)
            break
    if not api_node and not file_node:
        return None
    merged = dict(api_node or {})
    merged.update(file_node or {})
    if api_node and api_node.get("active") is not None:
        merged["active"] = api_node.get("active")
    return merged


def favorite_items():
    return list(load_favorites().get("nodes", {}).values())


def resolve_favorite(key):
    data = load_favorites()
    saved = data.get("nodes", {})
    if key in saved:
        return dict(saved[key])
    matches = [n for n in saved.values() if n.get("alias") == key]
    if len(matches) == 1:
        return dict(matches[0])
    if len(matches) > 1:
        raise RuntimeError(f"alias {key!r} matched multiple nodes; use node id instead")
    raise RuntimeError(f"saved node not found: {key}")


def save_one_favorite(node, alias=""):
    node = dict(node)
    node.pop("active", None)
    node = archive_config(node)
    node["alias"] = alias or node.get("alias", "")
    node["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S %z")
    data = load_favorites()
    data["nodes"][node["id"]] = node
    save_favorites(data)
    return node


def restore_saved_node(node):
    node = dict(node)
    favorite_config = Path(node.get("favorite_config_file") or "")
    if not node.get("config_text") and favorite_config.is_file():
        node["config_text"] = favorite_config.read_text(encoding="utf-8", errors="replace")
    if not node.get("config_text"):
        raise RuntimeError(f"saved config_text missing for {node.get('id')}")
    node = archive_config(node)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    Path(node["config_file"]).write_text(node["config_text"], encoding="utf-8")
    node["active"] = False

    current = load_nodes_file()
    replaced = False
    restored = []
    for item in current:
        if item.get("id") == node.get("id"):
            restored.append(node)
            replaced = True
        else:
            restored.append(item)
    if not replaced:
        restored.append(node)
    save_nodes_file(restored)
    return node


def print_nodes(items, limit):
    for idx, n in enumerate(items[:limit], 1):
        active = "*" if n.get("active") else " "
        print(
            f"{idx:>2}. {active} {n.get('id','')}\n"
            f"    {n.get('country','')} | quality={n.get('quality','')} | "
            f"type={n.get('ip_type','')} | status={n.get('probe_status','')} | "
            f"latency={n.get('latency_ms', 0)}ms\n"
            f"    owner={n.get('owner','')} | asn={n.get('asn','')}"
        )


def print_favorites(items, limit):
    if not items:
        print("No saved nodes yet.")
        return
    items = sorted(items, key=lambda n: n.get("saved_at", ""), reverse=True)
    for idx, n in enumerate(items[:limit], 1):
        alias = f" alias={n.get('alias')}" if n.get("alias") else ""
        print(
            f"{idx:>2}. {n.get('id','')}{alias}\n"
            f"    {n.get('country','')} | quality={n.get('quality','')} | "
            f"type={n.get('ip_type','')} | status={n.get('probe_status','')} | "
            f"latency={n.get('latency_ms', 0)}ms | saved={n.get('saved_at','')}\n"
            f"    owner={n.get('owner','')} | asn={n.get('asn','')}"
        )


def cmd_status(args):
    auth = load_auth()
    print("services:", flush=True)
    subprocess.run(["systemctl", "is-active", "aimilivpn"], check=False)
    subprocess.run(["systemctl", "is-active", "x-ui"], check=False)
    print("\nports:", flush=True)
    subprocess.run(["sh", "-lc", "ss -lntup | grep -E '18787|7928|9443' || true"], check=False)
    print("\ncurrent proxy ip:", flush=True)
    subprocess.run(
        [
            "curl",
            "-s",
            "--max-time",
            "15",
            "--proxy",
            f"socks5h://127.0.0.1:{auth['proxy_port']}",
            "https://api.ipify.org",
        ],
        check=False,
    )
    print()
    print("\nactive node:", flush=True)
    active = [n for n in nodes() if n.get("active")]
    print_nodes(active, 5)


def cmd_list(args):
    data = nodes()
    if args.country:
        data = [n for n in data if (n.get("country_short") or "").upper() == args.country.upper()]
    if args.residential:
        data = [
            n for n in data
            if n.get("ip_type") == "residential" or n.get("quality") == "normal"
        ]
    if args.available:
        data = [n for n in data if n.get("probe_status") == "available" or n.get("active")]
    data.sort(
        key=lambda n: (
            0 if n.get("active") else 1,
            0 if n.get("ip_type") == "residential" else 1,
            0 if n.get("quality") == "normal" else 1,
            0 if n.get("probe_status") == "available" else 1,
            int(n.get("latency_ms") or 999999),
        )
    )
    print_nodes(data, args.limit)


def cmd_test(args):
    s, base, _ = session()
    r = s.post(base + "/api/test_node", json={"id": args.node_id}, timeout=90)
    r.raise_for_status()
    payload = r.json()
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_connect(args):
    s, base, auth = session()
    r = s.post(base + "/api/connect", json={"id": args.node_id}, timeout=90)
    if r.status_code >= 400:
        print(r.text)
        r.raise_for_status()
    print(json.dumps(r.json(), ensure_ascii=False, indent=2), flush=True)
    time.sleep(args.wait)
    subprocess.run(
        [
            "curl",
            "-s",
            "--max-time",
            "15",
            "--proxy",
            f"socks5h://127.0.0.1:{auth['proxy_port']}",
            "https://api.ipify.org",
        ],
        check=False,
    )
    print()


def cmd_favorites(args):
    data = favorite_items()
    if args.country:
        data = [n for n in data if (n.get("country_short") or "").upper() == args.country.upper()]
    if args.residential:
        data = [
            n for n in data
            if n.get("ip_type") == "residential" or n.get("quality") == "normal"
        ]
    print_favorites(data, args.limit)


def cmd_save(args):
    node = find_live_node(args.node_id)
    if not node:
        raise RuntimeError(f"live node not found: {args.node_id}")
    saved = save_one_favorite(node, args.alias)
    print(f"saved: {saved['id']}")
    if saved.get("alias"):
        print(f"alias: {saved['alias']}")
    print(f"config: {saved.get('favorite_config_file')}")


def cmd_save_active(args):
    active = [n for n in nodes() if n.get("active")]
    if not active:
        raise RuntimeError("no active node found")
    node = find_live_node(active[0]["id"])
    if not node:
        raise RuntimeError(f"active node not found in node store: {active[0]['id']}")
    saved = save_one_favorite(node, args.alias)
    print(f"saved active: {saved['id']}")
    if saved.get("alias"):
        print(f"alias: {saved['alias']}")
    print(f"config: {saved.get('favorite_config_file')}")


def cmd_save_good(args):
    data = nodes()
    if args.country:
        data = [n for n in data if (n.get("country_short") or "").upper() == args.country.upper()]
    if args.residential:
        data = [
            n for n in data
            if n.get("ip_type") == "residential" or n.get("quality") == "normal"
        ]
    if args.available:
        data = [n for n in data if n.get("probe_status") == "available" or n.get("active")]
    data.sort(
        key=lambda n: (
            0 if n.get("active") else 1,
            0 if n.get("ip_type") == "residential" else 1,
            0 if n.get("quality") == "normal" else 1,
            0 if n.get("probe_status") == "available" else 1,
            int(n.get("latency_ms") or 999999),
        )
    )
    saved = []
    for node in data[:args.limit]:
        full_node = find_live_node(node["id"]) or node
        saved.append(save_one_favorite(full_node, ""))
    print(f"saved {len(saved)} node(s)")
    print_favorites(saved, args.limit)


def cmd_connect_saved(args):
    node = resolve_favorite(args.key)
    restore_saved_node(node)
    cmd_connect(argparse.Namespace(node_id=node["id"], wait=args.wait))


def cmd_refresh(args):
    s, base, _ = session()
    r = s.post(base + "/api/refresh_nodes", timeout=15)
    r.raise_for_status()
    print(json.dumps(r.json(), ensure_ascii=False, indent=2))
    if args.wait:
        time.sleep(args.wait)
        if args.save_good:
            cmd_save_good(argparse.Namespace(
                country=args.country,
                residential=args.residential,
                available=args.available,
                limit=args.limit,
            ))
        cmd_list(argparse.Namespace(country=args.country, residential=args.residential, available=False, limit=args.limit))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status").set_defaults(func=cmd_status)

    p = sub.add_parser("list")
    p.add_argument("--country", default="")
    p.add_argument("--residential", action="store_true")
    p.add_argument("--available", action="store_true")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("test")
    p.add_argument("node_id")
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("connect")
    p.add_argument("node_id")
    p.add_argument("--wait", type=int, default=8)
    p.set_defaults(func=cmd_connect)

    p = sub.add_parser("favorites")
    p.add_argument("--country", default="")
    p.add_argument("--residential", action="store_true")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_favorites)

    p = sub.add_parser("save")
    p.add_argument("node_id")
    p.add_argument("--alias", default="")
    p.set_defaults(func=cmd_save)

    p = sub.add_parser("save-active")
    p.add_argument("--alias", default="")
    p.set_defaults(func=cmd_save_active)

    p = sub.add_parser("save-good")
    p.add_argument("--country", default="")
    p.add_argument("--residential", action="store_true")
    p.add_argument("--available", action="store_true", default=True)
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_save_good)

    p = sub.add_parser("connect-saved")
    p.add_argument("key", help="saved node id or alias")
    p.add_argument("--wait", type=int, default=8)
    p.set_defaults(func=cmd_connect_saved)

    p = sub.add_parser("refresh")
    p.add_argument("--wait", type=int, default=12)
    p.add_argument("--country", default="")
    p.add_argument("--residential", action="store_true")
    p.add_argument("--available", action="store_true", default=True)
    p.add_argument("--save-good", action="store_true")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_refresh)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
'''


def run_remote(argv, host, ssh_user):
    cmd = [
        "ssh",
        "-F",
        "/dev/null",
        "-4",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        f"{ssh_user}@{host}",
        "python3 - " + " ".join(shlex.quote(arg) for arg in argv),
    ]
    proc = subprocess.run(cmd, input=REMOTE_SCRIPT, text=True)
    return proc.returncode


def main():
    parser = argparse.ArgumentParser(
        description="Terminal helper for selecting AimiliVPN/VPNGate nodes on the VPS."
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="VPS host or IP, or set AIMILI_HOST")
    parser.add_argument("--ssh-user", default=DEFAULT_SSH_USER, help="SSH user, or set AIMILI_SSH_USER")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    ns = parser.parse_args()
    if not ns.host:
        print("Set --host <vps-host> or AIMILI_HOST before running a command.")
        return 2
    if not ns.args:
        print("Usage examples:")
        print("  python3 aimili_node_cli.py --host <vps-host> status")
        print("  python3 aimili_node_cli.py --host <vps-host> list --country US --residential")
        print("  python3 aimili_node_cli.py --host <vps-host> test US_47.143.57.217_1785_tcp")
        print("  python3 aimili_node_cli.py --host <vps-host> connect US_47.143.57.217_1785_tcp")
        print("  python3 aimili_node_cli.py --host <vps-host> save-active --alias frontier")
        print("  python3 aimili_node_cli.py --host <vps-host> save-good --country US --residential")
        print("  python3 aimili_node_cli.py --host <vps-host> favorites")
        print("  python3 aimili_node_cli.py --host <vps-host> connect-saved frontier")
        print("  python3 aimili_node_cli.py --host <vps-host> refresh --country US --residential --save-good")
        return 2
    raise SystemExit(run_remote(ns.args, ns.host, ns.ssh_user))


if __name__ == "__main__":
    main()
