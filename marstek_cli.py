#!/usr/bin/env python3
"""
marstek_cli_en.py — Marstek Venus E/C Open API CLI  (Rev 2.0)

Read commands (--query):
    device  Device info (model, firmware, MACs)
    wifi    WiFi connection info
    ble     Bluetooth status
    bat     Battery details (capacity, temperature, charge flags)
    es      Energy System status (SOC, power flows, energy counters)
    em      Energy meter / CT (phase powers, cumulative energy)
    mode    Current operating mode + CT data

Set commands:
    --set-mode auto|ai|ups          Switch to Auto / AI / UPS mode
    --set-mode passive --power W    Passive mode with fixed discharge power [W]
    --set-dod  30..88               Depth of discharge [%]
    --set-led  on|off               LED panel on/off
    --set-ble  on|off               Bluetooth broadcasting on/off

Discovery:
    python marstek_cli_en.py        Auto-discover all Marstek devices in LAN
    python marstek_cli_en.py <ip>   Connect directly to known IP
"""

import argparse
import json
import socket
import time
from datetime import datetime
from typing import Optional

DEFAULT_PORT = 30000
TIMEOUT      = 2.0
RETRIES      = 3
RETRY_DELAY  = 0.5
REQUEST_ID   = 1


# ─── Helpers ──────────────────────────────────────────────────────────────────

def to_bool(val):
    """Handle API inconsistencies like 'ture'."""
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "ture", "1")
    return bool(val)


def safe_json(data: bytes) -> dict:
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        return {"error": "Invalid JSON response from device"}


def confirm(msg: str) -> bool:
    return input(f"{msg} [y/N]: ").strip().lower() == "y"


# ─── Transport ────────────────────────────────────────────────────────────────

def send_udp(ip: str, port: int, payload: dict) -> dict:
    msg = json.dumps(payload).encode("utf-8")
    req_id = payload.get("id")
    deadline = time.monotonic() + TIMEOUT * RETRIES

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(msg, (ip, port))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise socket.timeout
            s.settimeout(remaining)
            data, _ = s.recvfrom(4096)
            resp = safe_json(data)
            if "error" in resp or resp.get("id") == req_id:
                return resp


def query(ip: str, port: int, method: str, params: dict = None) -> dict:
    payload = {"id": REQUEST_ID, "method": method, "params": params or {"id": 0}}
    last_error = "Unknown error"

    for attempt in range(1, RETRIES + 1):
        try:
            resp = send_udp(ip, port, payload)
            if "error" in resp:
                return {"error": resp["error"]}
            return resp.get("result", {})
        except socket.timeout:
            last_error = f"Timeout after {RETRIES} attempts"
            if attempt < RETRIES:
                time.sleep(RETRY_DELAY)
        except Exception as e:
            return {"error": str(e)}

    return {"error": last_error, "skipped": True}


def discover_devices(port: int, timeout: float = 3.0) -> list:
    """UDP broadcast → collect all Marstek responses."""
    payload = json.dumps({
        "id": 0,
        "method": "Marstek.GetDevice",
        "params": {"ble_mac": "0"}
    }).encode("utf-8")

    found = []
    seen  = set()

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(timeout)
        s.sendto(payload, ("255.255.255.255", port))
        deadline = time.monotonic() + timeout

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                s.settimeout(remaining)
                data, addr = s.recvfrom(4096)
                resp   = safe_json(data)
                result = resp.get("result", {})
                key    = result.get("wifi_mac") or result.get("ble_mac")
                if result.get("device") and key and key not in seen:
                    seen.add(key)
                    result["_addr"] = addr[0]
                    found.append(result)
            except socket.timeout:
                break
            except Exception:
                continue

    return found


# ─── Formatting ───────────────────────────────────────────────────────────────

W = 40  # label column width

def fmt(label: str, value, unit: str = "") -> str:
    if value is None:
        return f"  {label:<{W}} —"
    return f"  {label:<{W}} {value}{' ' + unit if unit else ''}"


def fmt_wh(label: str, raw, scale: float = 1.0) -> str:
    """Energy value with optional scaling (×0.1 per Rev 2.0 spec)."""
    if raw is None:
        return f"  {label:<{W}} —"
    val = raw * scale
    if val >= 1000:
        return f"  {label:<{W}} {val / 1000:.2f} kWh"
    return f"  {label:<{W}} {val:.0f} Wh"


def fmt_error(r: dict) -> str:
    if r.get("skipped"):
        return f"  (not supported — {r['error']})"
    return f"  Error: {r['error']}"


def section(title: str):
    print(f"\n{'─' * 54}")
    print(f"  {title}")
    print(f"{'─' * 54}")


def ok_result(r: dict) -> bool:
    if "error" in r:
        print(fmt_error(r))
        return False
    return True


# ─── Read queries ─────────────────────────────────────────────────────────────

def show_device(ip, port):
    section("Device — Marstek.GetDevice")
    r = query(ip, port, "Marstek.GetDevice", {"ble_mac": "0"})
    if not ok_result(r):
        return
    print(fmt("Model",       r.get("device")))
    print(fmt("Firmware",    r.get("ver")))
    print(fmt("BLE MAC",     r.get("ble_mac")))
    print(fmt("WiFi MAC",    r.get("wifi_mac")))
    print(fmt("SSID",        r.get("wifi_name")))
    print(fmt("IP address",  r.get("ip")))


def show_wifi(ip, port):
    section("WiFi — Wifi.GetStatus")
    r = query(ip, port, "Wifi.GetStatus")
    if not ok_result(r):
        return
    print(fmt("SSID",        r.get("ssid")))
    print(fmt("IP address",  r.get("sta_ip")))
    print(fmt("Gateway",     r.get("sta_gate")))
    print(fmt("Subnet mask", r.get("sta_mask")))
    print(fmt("DNS",         r.get("sta_dns")))
    print(fmt("RSSI",        r.get("rssi"), "dBm"))


def show_ble(ip, port):
    section("Bluetooth — BLE.GetStatus")
    r = query(ip, port, "BLE.GetStatus")
    if not ok_result(r):
        return
    print(fmt("State",   r.get("state")))
    print(fmt("BLE MAC", r.get("ble_mac")))


def show_bat(ip, port):
    section("Battery — Bat.GetStatus")
    r = query(ip, port, "Bat.GetStatus")
    if not ok_result(r):
        return
    print(fmt("SOC",                   r.get("soc"), "%"))
    print(fmt_wh("Remaining",          r.get("bat_capacity")))
    print(fmt_wh("Rated capacity",     r.get("rated_capacity")))
    print(fmt("Temperature",           r.get("bat_temp"), "°C"))
    print(fmt("Charging allowed",      to_bool(r.get("charg_flag"))))
    print(fmt("Discharging allowed",   to_bool(r.get("dischrg_flag"))))


def show_es(ip, port):
    section("Energy System — ES.GetStatus")
    r = query(ip, port, "ES.GetStatus")
    if not ok_result(r):
        return
    print(fmt("SOC",                          r.get("bat_soc"), "%"))
    print(fmt_wh("Battery capacity",          r.get("bat_cap")))
    print(fmt("Battery power",                r.get("bat_power"), "W"))
    print(fmt("PV power",                     r.get("pv_power"), "W"))
    print(fmt("Grid (+ import / − export)",   r.get("ongrid_power"), "W"))
    print(fmt("Off-grid power",               r.get("offgrid_power"), "W"))
    print()
    print(fmt_wh("Total PV generated",        r.get("total_pv_energy")))
    print(fmt_wh("Total grid export",         r.get("total_grid_output_energy")))
    print(fmt_wh("Total grid import",         r.get("total_grid_input_energy")))
    print(fmt_wh("Total load / off-grid",     r.get("total_load_energy")))


def show_em(ip, port):
    section("Energy Meter — EM.GetStatus")
    r = query(ip, port, "EM.GetStatus")
    if not ok_result(r):
        return
    ct = r.get("ct_state")
    print(fmt("CT connected",  "Yes" if ct == 1 else "No"))
    print(fmt("Phase A",       r.get("a_power"), "W"))
    print(fmt("Phase B",       r.get("b_power"), "W"))
    print(fmt("Phase C",       r.get("c_power"), "W"))
    print(fmt("Total power",   r.get("total_power"), "W"))
    ie, oe = r.get("input_energy"), r.get("output_energy")
    if ie is not None or oe is not None:
        print()
        print(fmt_wh("Cumulative input (CT)",  ie, 0.1))
        print(fmt_wh("Cumulative output (CT)", oe, 0.1))


def show_mode(ip, port):
    section("Operating Mode — ES.GetMode")
    r = query(ip, port, "ES.GetMode")
    if not ok_result(r):
        return
    print(fmt("Mode",         r.get("mode")))
    print(fmt("SOC",          r.get("bat_soc"), "%"))
    print(fmt("Grid power",   r.get("ongrid_power"), "W"))
    print(fmt("Off-grid",     r.get("offgrid_power"), "W"))
    ct = r.get("ct_state")
    if ct is not None:
        print()
        print(fmt("CT connected",  "Yes" if ct == 1 else "No"))
        if ct == 1:
            print(fmt("Phase A (CT)",  r.get("a_power"), "W"))
            print(fmt("Phase B (CT)",  r.get("b_power"), "W"))
            print(fmt("Phase C (CT)",  r.get("c_power"), "W"))
            print(fmt("Total (CT)",    r.get("total_power"), "W"))
            ie, oe = r.get("input_energy"), r.get("output_energy")
            if ie is not None or oe is not None:
                print()
                print(fmt_wh("Cumulative input",  ie, 0.1))
                print(fmt_wh("Cumulative output", oe, 0.1))


QUERIES = {
    "device": show_device,
    "wifi":   show_wifi,
    "ble":    show_ble,
    "bat":    show_bat,
    "es":     show_es,
    "em":     show_em,
    "mode":   show_mode,
}


# ─── Set commands ─────────────────────────────────────────────────────────────

def set_mode(ip, port, mode: str, power: Optional[int]):
    MODES = {"auto": "Auto", "ai": "AI", "ups": "Ups", "passive": "Passive"}
    mode_key = mode.lower()
    if mode_key not in MODES:
        print(f"  Error: invalid mode '{mode}'. Valid: auto | ai | ups | passive")
        return
    if not confirm("⚠️  Change operating mode?"):
        return
    api_mode = MODES[mode_key]
    section(f"Set mode → {api_mode}")
    if api_mode == "Passive":
        if power is None:
            print("  Error: --power <W> is required for passive mode")
            return
        cfg = {"mode": api_mode, "passive_cfg": {"power": power, "cd_time": 30}}
    elif api_mode == "Ups":
        cfg = {"mode": api_mode, "ups_cfg": {"enable": 1}}
    elif api_mode == "AI":
        cfg = {"mode": api_mode, "ai_cfg": {"enable": 1}}
    else:
        cfg = {"mode": api_mode, "auto_cfg": {"enable": 1}}
    r = query(ip, port, "ES.SetMode", {"id": 0, "config": cfg})
    if not ok_result(r):
        return
    print(fmt("Result", "✓ Success" if to_bool(r.get("set_result")) else "✗ Failed"))
    if api_mode == "Passive":
        print(fmt("Target power", power, "W"))


def set_dod(ip, port, value: int):
    if not 30 <= value <= 88:
        print(f"  Error: DOD must be between 30 and 88 (got: {value})")
        return
    if not confirm("⚠️  Change depth of discharge?"):
        return
    section(f"Depth of discharge — DOD.SET → {value}%")
    r = query(ip, port, "DOD.SET", {"value": value})
    if not ok_result(r):
        return
    print(fmt("Result", "✓ Success" if to_bool(r.get("set_result")) else "✗ Failed"))


def set_led(ip, port, state: str):
    val   = 1 if state.lower() in ("on", "1") else 0
    label = "on" if val else "off"
    section(f"LED panel — Led.Ctrl → {label}")
    r = query(ip, port, "Led.Ctrl", {"state": val})
    if not ok_result(r):
        return
    print(fmt("Result", "✓ Success" if to_bool(r.get("set_result")) else "✗ Failed"))


def set_ble(ip, port, state: str):
    # enable=0 → broadcasting ON; enable=1 → broadcasting BLOCKED (per API spec)
    val   = 1 if state.lower() in ("off", "0") else 0
    label = "blocked" if val else "active"
    section(f"Bluetooth — Ble.Adv → {label}")
    r = query(ip, port, "Ble.Adv", {"enable": val})
    if not ok_result(r):
        return
    print(fmt("Result", "✓ Success" if to_bool(r.get("set_result")) else "✗ Failed"))


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Marstek Venus E/C — Local UDP API CLI (Rev 2.0)",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="Without IP: auto-discovery on the LAN"
    )
    parser.add_argument("ip", nargs="?", default=None,
                        help="Device IP address (optional — omit for auto-discovery)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"UDP port (default: {DEFAULT_PORT})")
    parser.add_argument("--query", choices=list(QUERIES.keys()), metavar="QUERY",
                        help="Query: " + " | ".join(QUERIES.keys()))
    parser.add_argument("--set-mode", metavar="MODE",
                        help="Mode: auto | ai | ups | passive  (passive requires --power)")
    parser.add_argument("--power", type=int, metavar="W",
                        help="Target power for passive mode [W]")
    parser.add_argument("--set-dod", type=int, metavar="PCT",
                        help="Set depth of discharge (30–88)")
    parser.add_argument("--set-led", metavar="on|off",
                        help="Turn LED panel on or off")
    parser.add_argument("--set-ble", metavar="on|off",
                        help="Turn Bluetooth broadcasting on or off")

    args = parser.parse_args()

    # ── Auto-Discovery ────────────────────────────────────────────────────────
    if args.ip is None:
        print(f"\nMarstek CLI  •  Auto-Discovery  •  {datetime.now().strftime('%H:%M:%S')}")
        print("\n  Scanning LAN for Marstek devices …")
        devices = discover_devices(args.port)
        if not devices:
            print("  No devices found. Is the Open API enabled in the Marstek app?")
            print()
            return
        print(f"  Found {len(devices)} device(s):\n")
        for i, d in enumerate(devices):
            ip_str = d.get("ip") or d.get("_addr")
            print(f"  [{i+1}]  {d.get('device','?'):<14}  "
                  f"IP: {ip_str:<16}  FW: {d.get('ver','?')}  MAC: {d.get('wifi_mac','?')}")
        print()
        if len(devices) == 1:
            chosen = devices[0]
        else:
            try:
                idx    = int(input("  Select device [1]: ").strip() or "1") - 1
                chosen = devices[idx]
            except (ValueError, IndexError):
                print("  Invalid selection.")
                return
        ip = chosen.get("ip") or chosen.get("_addr")
        print(f"  → {chosen.get('device')} @ {ip}\n")
    else:
        ip = args.ip

    print(f"\nMarstek CLI  •  {ip}:{args.port}  •  "
          f"{datetime.now().strftime('%H:%M:%S')}  •  Rev 2.0")

    # ── Dispatch ──────────────────────────────────────────────────────────────
    if args.set_mode:
        set_mode(ip, args.port, args.set_mode, args.power)
    elif args.set_dod is not None:
        set_dod(ip, args.port, args.set_dod)
    elif args.set_led:
        set_led(ip, args.port, args.set_led)
    elif args.set_ble:
        set_ble(ip, args.port, args.set_ble)
    elif args.query:
        QUERIES[args.query](ip, args.port)
    else:
        for fn in QUERIES.values():
            fn(ip, args.port)

    print()


if __name__ == "__main__":
    main()
