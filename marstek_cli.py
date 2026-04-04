#!/usr/bin/env python3
"""
marstek_cli.py — Marstek Venus E/C Open API CLI  (Rev 2.0)

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

Output options:
    --de                            German labels
    --json                          Machine-readable JSON output (language-independent)

Discovery:
    python marstek_cli.py           Auto-discover all Marstek devices in LAN
    python marstek_cli.py <ip>      Connect directly to known IP
"""

import argparse
import json
import socket
import sys
import time
from datetime import datetime
from typing import Optional

DEFAULT_PORT = 30000
TIMEOUT      = 2.0
RETRIES      = 3
RETRY_DELAY  = 0.5
REQUEST_ID   = 1

# Over Ethernet the device responds in ~10–100 ms with no inter-query delay
# needed. Over WiFi, UDP responses are unreliable below ~3.7 s spacing.
# A latency probe on the first GetDevice call auto-selects the right delay:
#   RTT < WIFI_RTT_THRESHOLD ms  →  Ethernet/good WiFi  →  no delay
#   RTT ≥ WIFI_RTT_THRESHOLD ms  →  WiFi                →  WIFI_QUERY_DELAY
WIFI_RTT_THRESHOLD = 150   # ms — clean split between Ethernet (~100) and WiFi
WIFI_QUERY_DELAY   = 4.0   # s  — safely clears the ~3.7 s WiFi rate-limit window
FORCE_DELAY        = None  # s  — set to e.g. 4.0 to skip auto-detection entirely


# ─── i18n ─────────────────────────────────────────────────────────────────────

LABELS = {
    "en": {
        # section titles
        "sec_device":  "Device — Marstek.GetDevice",
        "sec_wifi":    "WiFi — Wifi.GetStatus",
        "sec_ble":     "Bluetooth — BLE.GetStatus",
        "sec_bat":     "Battery — Bat.GetStatus",
        "sec_es":      "Energy System — ES.GetStatus",
        "sec_em":      "Energy Meter — EM.GetStatus",
        "sec_mode":    "Operating Mode — ES.GetMode",
        # device
        "model":       "Model",
        "firmware":    "Firmware",
        "ble_mac":     "BLE MAC",
        "wifi_mac":    "WiFi MAC",
        "ssid":        "SSID",
        "ip_address":  "IP address",
        # wifi
        "gateway":     "Gateway",
        "subnet":      "Subnet mask",
        "dns":         "DNS",
        "rssi":        "RSSI",
        # ble
        "ble_state":   "State",
        # bat
        "soc":         "SOC",
        "remaining":   "Remaining",
        "rated_cap":   "Rated capacity",
        "temp":        "Temperature",
        "charg_ok":    "Charging allowed",
        "discharg_ok": "Discharging allowed",
        # es
        "bat_cap":     "Battery capacity",
        "bat_power":   "Battery power",
        "pv_power":    "PV power",
        "grid_power":  "Grid (+ import / − export)",
        "offgrid":     "Off-grid power",
        "total_pv":    "Total PV generated",
        "total_exp":   "Total grid export",
        "total_imp":   "Total grid import",
        "total_load":  "Total load / off-grid",
        # em / mode
        "ct_conn":     "CT connected",
        "phase_a":     "Phase A",
        "phase_b":     "Phase B",
        "phase_c":     "Phase C",
        "total_pow":   "Total power",
        "cum_in":      "Cumulative input (CT)",
        "cum_out":     "Cumulative output (CT)",
        "ct_yes":      "Yes",
        "ct_no":       "No",
        # mode
        "mode":        "Mode",
        "grid_pow":    "Grid power",
        "phase_a_ct":  "Phase A (CT)",
        "phase_b_ct":  "Phase B (CT)",
        "phase_c_ct":  "Phase C (CT)",
        "total_ct":    "Total (CT)",
        "cum_in2":     "Cumulative input",
        "cum_out2":    "Cumulative output",
        # set results
        "result":      "Result",
        "success":     "✓ Success",
        "failed":      "✗ Failed",
        "target_pow":  "Target power",
        # errors / prompts
        "err_mode":    "Error: invalid mode '{}'. Valid: auto | ai | ups | passive",
        "err_power":   "Error: --power <W> is required for passive mode",
        "err_dod":     "Error: DOD must be between 30 and 88 (got: {})",
        "err_generic": "Error: {}",
        "not_supp":    "(not supported — {})",
        "confirm_mode":"⚠️  Change operating mode?",
        "confirm_dod": "⚠️  Change depth of discharge?",
        # discovery
        "disc_scan":   "Scanning LAN for Marstek devices …",
        "disc_none":   "No devices found. Is the Open API enabled in the Marstek app?",
        "disc_found":  "Found {} device(s):",
        "disc_select": "Select device [1]: ",
        "disc_invalid":"Invalid selection.",
        "disc_arrow":  "→",
        # set sections
        "sec_set_mode":"Set mode → {}",
        "sec_dod":     "Depth of discharge — DOD.SET → {}%",
        "sec_led":     "LED panel — Led.Ctrl → {}",
        "sec_ble_adv": "Bluetooth — Ble.Adv → {}",
        "led_on":      "on",
        "led_off":     "off",
        "ble_active":  "active",
        "ble_blocked": "blocked",
    },
    "de": {
        "sec_device":  "Gerät — Marstek.GetDevice",
        "sec_wifi":    "WLAN — Wifi.GetStatus",
        "sec_ble":     "Bluetooth — BLE.GetStatus",
        "sec_bat":     "Batterie — Bat.GetStatus",
        "sec_es":      "Energy System — ES.GetStatus",
        "sec_em":      "Energiezähler — EM.GetStatus",
        "sec_mode":    "Betriebsmodus — ES.GetMode",
        "model":       "Modell",
        "firmware":    "Firmware",
        "ble_mac":     "BLE MAC",
        "wifi_mac":    "WiFi MAC",
        "ssid":        "SSID",
        "ip_address":  "IP-Adresse",
        "gateway":     "Gateway",
        "subnet":      "Subnetzmaske",
        "dns":         "DNS",
        "rssi":        "RSSI",
        "ble_state":   "Status",
        "soc":         "SOC",
        "remaining":   "Verbleibend",
        "rated_cap":   "Nennkapazität",
        "temp":        "Temperatur",
        "charg_ok":    "Laden erlaubt",
        "discharg_ok": "Entladen erlaubt",
        "bat_cap":     "Batteriekapazität",
        "bat_power":   "Batterieleistung",
        "pv_power":    "PV-Leistung",
        "grid_power":  "Netz (+ Bezug / − Einspeisung)",
        "offgrid":     "Offgrid-Leistung",
        "total_pv":    "Gesamt PV erzeugt",
        "total_exp":   "Gesamt Netzeinspeisung",
        "total_imp":   "Gesamt Netzbezug",
        "total_load":  "Gesamt Last/Offgrid",
        "ct_conn":     "CT verbunden",
        "phase_a":     "Phase A",
        "phase_b":     "Phase B",
        "phase_c":     "Phase C",
        "total_pow":   "Gesamtleistung",
        "cum_in":      "Kumulierter Eingang (CT)",
        "cum_out":     "Kumulierter Ausgang (CT)",
        "ct_yes":      "Ja",
        "ct_no":       "Nein",
        "mode":        "Modus",
        "grid_pow":    "Netzleistung",
        "phase_a_ct":  "Phase A (CT)",
        "phase_b_ct":  "Phase B (CT)",
        "phase_c_ct":  "Phase C (CT)",
        "total_ct":    "Gesamt (CT)",
        "cum_in2":     "Kumulierter Eingang",
        "cum_out2":    "Kumulierter Ausgang",
        "result":      "Ergebnis",
        "success":     "✓ Erfolgreich",
        "failed":      "✗ Fehlgeschlagen",
        "target_pow":  "Sollleistung",
        "err_mode":    "Fehler: Ungültiger Modus '{}'. Gültig: auto | ai | ups | passive",
        "err_power":   "Fehler: --power <W> ist für Passive-Modus erforderlich",
        "err_dod":     "Fehler: DOD muss zwischen 30 und 88 liegen (angegeben: {})",
        "err_generic": "Fehler: {}",
        "not_supp":    "(nicht unterstützt — {})",
        "confirm_mode":"⚠️  Gerätemodus ändern?",
        "confirm_dod": "⚠️  Entladetiefe ändern?",
        "disc_scan":   "Suche nach Marstek-Geräten im LAN …",
        "disc_none":   "Keine Geräte gefunden. Ist die Open API in der App aktiviert?",
        "disc_found":  "{} Gerät(e) gefunden:",
        "disc_select": "Gerät auswählen [1]: ",
        "disc_invalid":"Ungültige Auswahl.",
        "disc_arrow":  "→",
        "sec_set_mode":"Modus setzen → {}",
        "sec_dod":     "Entladetiefe — DOD.SET → {}%",
        "sec_led":     "LED — Led.Ctrl → {}",
        "sec_ble_adv": "Bluetooth — Ble.Adv → {}",
        "led_on":      "ein",
        "led_off":     "aus",
        "ble_active":  "aktiv",
        "ble_blocked": "gesperrt",
    },
}

# Active language — overridden in main() via --de flag
_lang = "en"

def t(key: str, *args) -> str:
    s = LABELS[_lang].get(key, LABELS["en"].get(key, key))
    return s.format(*args) if args else s


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


def confirm(key: str) -> bool:
    return input(f"{t(key)} [y/N]: ").strip().lower() == "y"


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


def send_udp_timed(ip: str, port: int, payload: dict) -> tuple:
    """Like send_udp but also returns RTT in ms. Returns (result, rtt_ms)."""
    msg    = json.dumps(payload).encode("utf-8")
    req_id = payload.get("id")
    t0     = time.monotonic()
    deadline = t0 + TIMEOUT * RETRIES

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(msg, (ip, port))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise socket.timeout
            s.settimeout(remaining)
            data, _ = s.recvfrom(4096)
            rtt_ms = (time.monotonic() - t0) * 1000
            resp = safe_json(data)
            if "error" in resp or resp.get("id") == req_id:
                return resp, rtt_ms


def probe_link(ip: str, port: int) -> Optional[float]:
    """Send a single GetDevice and return RTT in ms, or None on timeout."""
    payload = {"id": REQUEST_ID, "method": "Marstek.GetDevice", "params": {"ble_mac": "0"}}
    try:
        _, rtt_ms = send_udp_timed(ip, port, payload)
        return rtt_ms
    except (socket.timeout, OSError):
        return None


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

W = 42  # label column width

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
        return f"  {t('not_supp', r['error'])}"
    return f"  {t('err_generic', r['error'])}"


def section(title: str):
    print(f"\n{'─' * 56}")
    print(f"  {title}")
    print(f"{'─' * 56}")


def ok_result(r: dict) -> bool:
    if "error" in r:
        print(fmt_error(r))
        return False
    return True


# ─── JSON output helpers ──────────────────────────────────────────────────────

# Collector for --json mode: flat dict
_json_output: dict = {}
_json_mode = False


def json_collect(section_key: str, data: dict):
    _json_output[section_key] = data


def scale_energy(raw, scale=1.0):
    return round(raw * scale, 1) if raw is not None else None


# ─── Read queries ─────────────────────────────────────────────────────────────

def show_device(ip, port):
    r = query(ip, port, "Marstek.GetDevice", {"ble_mac": "0"})
    if _json_mode:
        if "error" not in r:
            json_collect("device", {
                "model": r.get("device"), "firmware": r.get("ver"),
                "ble_mac": r.get("ble_mac"), "wifi_mac": r.get("wifi_mac"),
                "ssid": r.get("wifi_name"), "ip": r.get("ip"),
            })
        return
    section(t("sec_device"))
    if not ok_result(r): return
    print(fmt(t("model"),      r.get("device")))
    print(fmt(t("firmware"),   r.get("ver")))
    print(fmt(t("ble_mac"),    r.get("ble_mac")))
    print(fmt(t("wifi_mac"),   r.get("wifi_mac")))
    print(fmt(t("ssid"),       r.get("wifi_name")))
    print(fmt(t("ip_address"), r.get("ip")))


def show_wifi(ip, port):
    r = query(ip, port, "Wifi.GetStatus")
    if _json_mode:
        if "error" not in r:
            json_collect("wifi", {
                "ssid": r.get("ssid"), "ip": r.get("sta_ip"),
                "gateway": r.get("sta_gate"), "subnet": r.get("sta_mask"),
                "dns": r.get("sta_dns"), "rssi_dbm": r.get("rssi"),
            })
        return
    section(t("sec_wifi"))
    if not ok_result(r): return
    print(fmt(t("ssid"),       r.get("ssid")))
    print(fmt(t("ip_address"), r.get("sta_ip")))
    print(fmt(t("gateway"),    r.get("sta_gate")))
    print(fmt(t("subnet"),     r.get("sta_mask")))
    print(fmt(t("dns"),        r.get("sta_dns")))
    print(fmt(t("rssi"),       r.get("rssi"), "dBm"))


def show_ble(ip, port):
    r = query(ip, port, "BLE.GetStatus")
    if _json_mode:
        if "error" not in r:
            json_collect("ble", {"state": r.get("state"), "ble_mac": r.get("ble_mac")})
        return
    section(t("sec_ble"))
    if not ok_result(r): return
    print(fmt(t("ble_state"), r.get("state")))
    print(fmt(t("ble_mac"),   r.get("ble_mac")))


def show_bat(ip, port):
    r = query(ip, port, "Bat.GetStatus")
    if _json_mode:
        if "error" not in r:
            json_collect("battery", {
                "soc_pct": r.get("soc"),
                "remaining_wh": r.get("bat_capacity"),
                "rated_wh": r.get("rated_capacity"),
                "temp_c": r.get("bat_temp"),
                "charging_allowed": to_bool(r.get("charg_flag")),
                "discharging_allowed": to_bool(r.get("dischrg_flag")),
            })
        return
    section(t("sec_bat"))
    if not ok_result(r): return
    print(fmt(t("soc"),         r.get("soc"), "%"))
    print(fmt_wh(t("remaining"),r.get("bat_capacity")))
    print(fmt_wh(t("rated_cap"),r.get("rated_capacity")))
    print(fmt(t("temp"),        r.get("bat_temp"), "°C"))
    print(fmt(t("charg_ok"),    to_bool(r.get("charg_flag"))))
    print(fmt(t("discharg_ok"), to_bool(r.get("dischrg_flag"))))


def show_es(ip, port):
    r = query(ip, port, "ES.GetStatus")
    if _json_mode:
        if "error" not in r:
            json_collect("energy_system", {
                "soc_pct": r.get("bat_soc"),
                "battery_capacity_wh": r.get("bat_cap"),
                "battery_power_w": r.get("bat_power"),  # null = standby, 0 = active idle
                "pv_power_w": r.get("pv_power") or 0,
                "grid_power_w": r.get("ongrid_power") or 0,
                "offgrid_power_w": r.get("offgrid_power") or 0,
                "total_pv_wh": r.get("total_pv_energy"),
                "total_grid_export_wh": r.get("total_grid_output_energy"),
                "total_grid_import_wh": r.get("total_grid_input_energy"),
                "total_load_wh": r.get("total_load_energy"),
            })
        return
    section(t("sec_es"))
    if not ok_result(r): return
    print(fmt(t("soc"),         r.get("bat_soc"), "%"))
    print(fmt_wh(t("bat_cap"),  r.get("bat_cap")))
    print(fmt(t("bat_power"),   r.get("bat_power"), "W"))
    print(fmt(t("pv_power"),    r.get("pv_power"), "W"))
    print(fmt(t("grid_power"),  r.get("ongrid_power"), "W"))
    print(fmt(t("offgrid"),     r.get("offgrid_power"), "W"))
    print()
    print(fmt_wh(t("total_pv"),  r.get("total_pv_energy")))
    print(fmt_wh(t("total_exp"), r.get("total_grid_output_energy")))
    print(fmt_wh(t("total_imp"), r.get("total_grid_input_energy")))
    print(fmt_wh(t("total_load"),r.get("total_load_energy")))


def show_em(ip, port):
    r = query(ip, port, "EM.GetStatus")
    if _json_mode:
        if "error" not in r:
            ie, oe = r.get("input_energy"), r.get("output_energy")
            json_collect("energy_meter", {
                "ct_connected": r.get("ct_state") == 1,
                "phase_a_w": r.get("a_power"),
                "phase_b_w": r.get("b_power"),
                "phase_c_w": r.get("c_power"),
                "total_w": r.get("total_power"),
                "cumulative_input_wh":  scale_energy(ie, 0.1),
                "cumulative_output_wh": scale_energy(oe, 0.1),
            })
        return
    section(t("sec_em"))
    if not ok_result(r): return
    ct = r.get("ct_state")
    print(fmt(t("ct_conn"),  t("ct_yes") if ct == 1 else t("ct_no")))
    print(fmt(t("phase_a"),  r.get("a_power"), "W"))
    print(fmt(t("phase_b"),  r.get("b_power"), "W"))
    print(fmt(t("phase_c"),  r.get("c_power"), "W"))
    print(fmt(t("total_pow"),r.get("total_power"), "W"))
    ie, oe = r.get("input_energy"), r.get("output_energy")
    if ie is not None or oe is not None:
        print()
        print(fmt_wh(t("cum_in"),  ie, 0.1))
        print(fmt_wh(t("cum_out"), oe, 0.1))


def show_mode(ip, port):
    r = query(ip, port, "ES.GetMode")
    if _json_mode:
        if "error" not in r:
            ct = r.get("ct_state")
            ie, oe = r.get("input_energy"), r.get("output_energy")
            json_collect("operating_mode", {
                "mode": r.get("mode"),
                "soc_pct": r.get("bat_soc"),
                "grid_power_w": r.get("ongrid_power"),
                "offgrid_power_w": r.get("offgrid_power"),
                "ct_connected": ct == 1 if ct is not None else None,
                "phase_a_w": r.get("a_power") if ct == 1 else None,
                "phase_b_w": r.get("b_power") if ct == 1 else None,
                "phase_c_w": r.get("c_power") if ct == 1 else None,
                "total_w":   r.get("total_power") if ct == 1 else None,
                "cumulative_input_wh":  scale_energy(ie, 0.1) if ct == 1 else None,
                "cumulative_output_wh": scale_energy(oe, 0.1) if ct == 1 else None,
            })
        return
    section(t("sec_mode"))
    if not ok_result(r): return
    print(fmt(t("mode"),     r.get("mode")))
    print(fmt(t("soc"),      r.get("bat_soc"), "%"))
    print(fmt(t("grid_pow"), r.get("ongrid_power"), "W"))
    print(fmt(t("offgrid"),  r.get("offgrid_power"), "W"))
    ct = r.get("ct_state")
    if ct is not None:
        print()
        print(fmt(t("ct_conn"), t("ct_yes") if ct == 1 else t("ct_no")))
        if ct == 1:
            print(fmt(t("phase_a_ct"), r.get("a_power"), "W"))
            print(fmt(t("phase_b_ct"), r.get("b_power"), "W"))
            print(fmt(t("phase_c_ct"), r.get("c_power"), "W"))
            print(fmt(t("total_ct"),   r.get("total_power"), "W"))
            ie, oe = r.get("input_energy"), r.get("output_energy")
            if ie is not None or oe is not None:
                print()
                print(fmt_wh(t("cum_in2"), ie, 0.1))
                print(fmt_wh(t("cum_out2"),oe, 0.1))


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
        print(f"  {t('err_mode', mode)}")
        return
    if not confirm("confirm_mode"):
        return
    api_mode = MODES[mode_key]
    section(t("sec_set_mode", api_mode))
    if api_mode == "Passive":
        if power is None:
            print(f"  {t('err_power')}")
            return
        cfg = {"mode": api_mode, "passive_cfg": {"power": power, "cd_time": 30}}
    elif api_mode == "Ups":
        cfg = {"mode": api_mode, "ups_cfg": {"enable": 1}}
    elif api_mode == "AI":
        cfg = {"mode": api_mode, "ai_cfg": {"enable": 1}}
    else:
        cfg = {"mode": api_mode, "auto_cfg": {"enable": 1}}
    r = query(ip, port, "ES.SetMode", {"id": 0, "config": cfg})
    if not ok_result(r): return
    ok = to_bool(r.get("set_result"))
    print(fmt(t("result"), t("success") if ok else t("failed")))
    if api_mode == "Passive":
        print(fmt(t("target_pow"), power, "W"))


def set_dod(ip, port, value: int):
    if not 30 <= value <= 88:
        print(f"  {t('err_dod', value)}")
        return
    if not confirm("confirm_dod"):
        return
    section(t("sec_dod", value))
    r = query(ip, port, "DOD.SET", {"value": value})
    if not ok_result(r): return
    print(fmt(t("result"), t("success") if to_bool(r.get("set_result")) else t("failed")))


def set_led(ip, port, state: str):
    val   = 1 if state.lower() in ("on", "ein", "1") else 0
    label = t("led_on") if val else t("led_off")
    section(t("sec_led", label))
    r = query(ip, port, "Led.Ctrl", {"state": val})
    if not ok_result(r): return
    print(fmt(t("result"), t("success") if to_bool(r.get("set_result")) else t("failed")))


def set_ble(ip, port, state: str):
    # enable=0 → broadcasting ON; enable=1 → broadcasting BLOCKED
    val   = 1 if state.lower() in ("off", "aus", "0") else 0
    label = t("ble_blocked") if val else t("ble_active")
    section(t("sec_ble_adv", label))
    r = query(ip, port, "Ble.Adv", {"enable": val})
    if not ok_result(r): return
    print(fmt(t("result"), t("success") if to_bool(r.get("set_result")) else t("failed")))


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    global _lang, _json_mode

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
    parser.add_argument("--de", action="store_true",
                        help="German output labels")
    parser.add_argument("--json", action="store_true", dest="json_out",
                        help="Machine-readable JSON output")
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
    parser.add_argument("--delay", type=float, metavar="S", default=None,
                        help="Fixed inter-query delay in seconds (skips auto-detection). "
                             "Use 0 to force no delay, 4.0 for reliable WiFi operation.")

    args = parser.parse_args()

    _lang      = "de" if args.de else "en"  # English is default
    _json_mode = args.json_out

    # ── Auto-Discovery ────────────────────────────────────────────────────────
    if args.ip is None:
        if not _json_mode:
            print(f"\nMarstek CLI  •  Auto-Discovery  •  {datetime.now().strftime('%H:%M:%S')}")
            print(f"\n  {t('disc_scan')}")
        devices = discover_devices(args.port)
        if not devices:
            if _json_mode:
                print(json.dumps({"error": "no devices found"}, indent=2))
            else:
                print(f"  {t('disc_none')}")
                print()
            return
        if not _json_mode:
            print(f"  {t('disc_found', len(devices))}\n")
            for i, d in enumerate(devices):
                ip_str = d.get("ip") or d.get("_addr")
                print(f"  [{i+1}]  {d.get('device','?'):<14}  "
                      f"IP: {ip_str:<16}  FW: {d.get('ver','?')}  MAC: {d.get('wifi_mac','?')}")
            print()
        if len(devices) == 1:
            chosen = devices[0]
        else:
            if _json_mode:
                chosen = devices[0]  # non-interactive: pick first
            else:
                try:
                    idx    = int(input(f"  {t('disc_select')}").strip() or "1") - 1
                    chosen = devices[idx]
                except (ValueError, IndexError):
                    print(f"  {t('disc_invalid')}")
                    return
        ip = chosen.get("ip") or chosen.get("_addr")
        if not _json_mode:
            print(f"  {t('disc_arrow')} {chosen.get('device')} @ {ip}\n")
    else:
        ip = args.ip

    if not _json_mode:
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
        # Determine inter-query delay (priority: --delay > FORCE_DELAY > auto-detect)
        if args.delay is not None:
            inter_delay = args.delay
            link_label  = f"manual (--delay {inter_delay} s)"
        elif FORCE_DELAY is not None:
            inter_delay = FORCE_DELAY
            link_label  = f"manual (FORCE_DELAY = {inter_delay} s)"
        else:
            rtt = probe_link(ip, args.port)
            if rtt is None or rtt >= WIFI_RTT_THRESHOLD:
                inter_delay = WIFI_QUERY_DELAY
                link_label  = (f"WiFi (RTT {'timeout' if rtt is None else f'{rtt:.0f} ms'}"
                               f" ≥ {WIFI_RTT_THRESHOLD} ms → delay {inter_delay} s)")
            else:
                inter_delay = 0.0
                link_label  = f"Ethernet (RTT {rtt:.0f} ms < {WIFI_RTT_THRESHOLD} ms → no delay)"
        if not _json_mode:
            print(f"  Link: {link_label}\n")

        fns = list(QUERIES.values())
        for i, fn in enumerate(fns):
            fn(ip, args.port)
            if inter_delay and i < len(fns) - 1:
                time.sleep(inter_delay)

    # ── JSON flush ────────────────────────────────────────────────────────────
    if _json_mode:
        output = {
            "timestamp": datetime.now().isoformat(),
            "device_ip": ip,
            "port": args.port,
            "data": _json_output,
        }
        print(json.dumps(output, indent=2))
    else:
        print()


if __name__ == "__main__":
    main()
