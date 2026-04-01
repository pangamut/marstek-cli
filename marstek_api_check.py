#!/usr/bin/env python3
"""
marstek_api_check.py — Marstek Venus E/C  API Behaviour Analyser

Probes every known API command, measures round-trip timing, logs raw
payloads, detects type anomalies and unexpected fields, and stress-tests
the device for rate-limit behaviour.

Usage:
    python marstek_api_check.py <ip>
    python marstek_api_check.py <ip> --rounds 20 --delay 0.2
    python marstek_api_check.py <ip> --raw
    python marstek_api_check.py <ip> --report results.json
    python marstek_api_check.py <ip> --stress --rounds 50 --delay 0.05
"""

import argparse
import json
import math
import socket
import statistics
import time
from datetime import datetime
from typing import Optional

DEFAULT_PORT  = 30000
TIMEOUT       = 4.5     # device has ~3.8 s rate-limit window; must exceed it
RETRIES       = 1       # single attempt per probe (we want raw behaviour)


# ─── Known API commands ───────────────────────────────────────────────────────

COMMANDS = [
    {
        "id":     "GetDevice",
        "method": "Marstek.GetDevice",
        "params": {"ble_mac": "0"},
        "expect": {
            "device":    str,
            "ver":       (int, str),
            "ble_mac":   str,
            "wifi_mac":  str,
            "wifi_name": str,
            "ip":        str,
        },
    },
    {
        "id":     "Wifi.GetStatus",
        "method": "Wifi.GetStatus",
        "params": {"id": 0},
        "expect": {
            "ssid":     (str, type(None)),
            "rssi":     (int, float),
            "sta_ip":   (str, type(None)),
            "sta_gate": (str, type(None)),
            "sta_mask": (str, type(None)),
            "sta_dns":  (str, type(None)),
        },
    },
    {
        "id":     "BLE.GetStatus",
        "method": "BLE.GetStatus",
        "params": {"id": 0},
        "expect": {
            "state":   str,
            "ble_mac": str,
        },
    },
    {
        "id":     "Bat.GetStatus",
        "method": "Bat.GetStatus",
        "params": {"id": 0},
        "expect": {
            "soc":           (int, float, str),
            "charg_flag":    (bool, str),
            "dischrg_flag":  (bool, str),
            "bat_temp":      (int, float, type(None)),
            "bat_capacity":  (int, float, type(None)),
            "rated_capacity":(int, float, type(None)),
        },
    },
    {
        "id":     "ES.GetStatus",
        "method": "ES.GetStatus",
        "params": {"id": 0},
        "expect": {
            "bat_soc":                  (int, float, type(None)),
            "bat_cap":                  (int, float, type(None)),
            "pv_power":                 (int, float, type(None)),
            "ongrid_power":             (int, float, type(None)),
            "offgrid_power":            (int, float, type(None)),
            "bat_power":                (int, float, type(None)),
            "total_pv_energy":          (int, float, type(None)),
            "total_grid_output_energy": (int, float, type(None)),
            "total_grid_input_energy":  (int, float, type(None)),
            "total_load_energy":        (int, float, type(None)),
        },
    },
    {
        "id":     "ES.GetMode",
        "method": "ES.GetMode",
        "params": {"id": 0},
        "expect": {
            "mode":         (str, type(None)),
            "ongrid_power": (int, float, type(None)),
            "offgrid_power":(int, float, type(None)),
            "bat_soc":      (int, float, type(None)),
            "ct_state":     (int, type(None)),
            "a_power":      (int, float, type(None)),
            "b_power":      (int, float, type(None)),
            "c_power":      (int, float, type(None)),
            "total_power":  (int, float, type(None)),
            "input_energy": (int, float, type(None)),
            "output_energy":(int, float, type(None)),
        },
    },
    {
        "id":     "EM.GetStatus",
        "method": "EM.GetStatus",
        "params": {"id": 0},
        "expect": {
            "ct_state":     (int, type(None)),
            "a_power":      (int, float, type(None)),
            "b_power":      (int, float, type(None)),
            "c_power":      (int, float, type(None)),
            "total_power":  (int, float, type(None)),
            "input_energy": (int, float, type(None)),
            "output_energy":(int, float, type(None)),
        },
    },
    # Invalid command — to probe error handling
    {
        "id":     "INVALID.Command",
        "method": "INVALID.Command",
        "params": {"id": 0},
        "expect": {},
        "expect_error": True,
    },
]


# ─── Transport ────────────────────────────────────────────────────────────────

def send_udp_raw(ip: str, port: int, payload: dict, timeout: float) -> tuple:
    """
    Send UDP payload, return (response_dict, rtt_ms, raw_bytes).
    Raises socket.timeout on timeout.
    """
    msg = json.dumps(payload).encode("utf-8")
    req_id = payload.get("id")

    t0 = time.monotonic()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        s.sendto(msg, (ip, port))
        # Drain responses until we find ours (or timeout)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise socket.timeout
            s.settimeout(remaining)
            raw, _ = s.recvfrom(4096)
            rtt_ms = (time.monotonic() - t0) * 1000
            try:
                resp = json.loads(raw.decode("utf-8"))
            except Exception:
                resp = {"error": "parse_error", "raw": raw.decode("utf-8", errors="replace")}
            if "error" in resp or resp.get("id") == req_id:
                return resp, rtt_ms, raw


def probe(ip: str, port: int, cmd: dict) -> dict:
    """Run a single probe of one command. Returns result record."""
    payload = {
        "id":     1,
        "method": cmd["method"],
        "params": cmd.get("params", {"id": 0}),
    }
    record = {
        "command":     cmd["id"],
        "method":      cmd["method"],
        "timestamp":   datetime.now().isoformat(),
        "rtt_ms":      None,
        "status":      None,       # "ok" | "error" | "timeout" | "parse_error"
        "raw_request": json.dumps(payload),
        "raw_response": None,
        "result":      None,
        "error":       None,
        "type_issues": [],
        "unknown_fields": [],
        "notable_values": [],
    }

    try:
        resp, rtt_ms, raw = send_udp_raw(ip, port, payload, TIMEOUT)
        record["rtt_ms"]       = round(rtt_ms, 2)
        record["raw_response"] = raw.decode("utf-8", errors="replace")

        if "error" in resp:
            record["status"] = "error"
            record["error"]  = resp["error"]
            if cmd.get("expect_error"):
                record["status"] = "ok"  # expected error → pass
        else:
            result = resp.get("result", {})
            record["result"] = result
            record["status"] = "ok"

            # Type checking
            for field, expected_types in cmd.get("expect", {}).items():
                val = result.get(field, "__MISSING__")
                if val == "__MISSING__":
                    record["type_issues"].append(f"MISSING field: {field}")
                    continue
                if not isinstance(expected_types, tuple):
                    expected_types = (expected_types,)
                if val is not None and not isinstance(val, expected_types):
                    record["type_issues"].append(
                        f"{field}: expected {[t.__name__ for t in expected_types]}, "
                        f"got {type(val).__name__} = {repr(val)}"
                    )

            # Detect unexpected fields
            known = set(cmd.get("expect", {}).keys()) | {"id"}
            for k in result:
                if k not in known:
                    record["unknown_fields"].append(f"{k} = {repr(result[k])}")

            # Notable values (API quirks like "ture", etc.)
            for k, v in result.items():
                if isinstance(v, str) and v.lower() in ("ture", "flase", "fasle"):
                    record["notable_values"].append(
                        f"⚠️  Typo bool: {k} = {repr(v)}"
                    )
                if v is None:
                    record["notable_values"].append(f"null: {k}")

    except socket.timeout:
        record["status"] = "timeout"
        record["error"]  = f"No response within {TIMEOUT}s"

    except Exception as e:
        record["status"] = "parse_error"
        record["error"]  = str(e)

    return record


# ─── Statistics ───────────────────────────────────────────────────────────────

def summarise(records: list) -> dict:
    """Compute per-command timing and reliability stats."""
    by_cmd = {}
    for r in records:
        cmd = r["command"]
        if cmd not in by_cmd:
            by_cmd[cmd] = []
        by_cmd[cmd].append(r)

    summary = {}
    for cmd, recs in by_cmd.items():
        rtts    = [r["rtt_ms"] for r in recs if r["rtt_ms"] is not None]
        ok      = sum(1 for r in recs if r["status"] == "ok")
        timeout = sum(1 for r in recs if r["status"] == "timeout")
        error   = sum(1 for r in recs if r["status"] == "error")
        total   = len(recs)

        summary[cmd] = {
            "total":        total,
            "ok":           ok,
            "timeout":      timeout,
            "error":        error,
            "success_rate": f"{ok/total*100:.0f}%",
            "rtt_min_ms":   round(min(rtts), 2) if rtts else None,
            "rtt_max_ms":   round(max(rtts), 2) if rtts else None,
            "rtt_avg_ms":   round(statistics.mean(rtts), 2) if rtts else None,
            "rtt_stdev_ms": round(statistics.stdev(rtts), 2) if len(rtts) > 1 else None,
            "type_issues":  list({i for r in recs for i in r["type_issues"]}),
            "unknown_fields": list({f for r in recs for f in r["unknown_fields"]}),
            "notable_values": list({v for r in recs for v in r["notable_values"]}),
        }
    return summary


# ─── Report printing ──────────────────────────────────────────────────────────

SEP = "─" * 60

def print_summary(summary: dict, rounds: int):
    print(f"\n{SEP}")
    print(f"  SUMMARY  ({rounds} round(s) per command)")
    print(SEP)

    col = 24
    header = (f"  {'Command':<{col}}  {'OK':>4}  {'T/O':>4}  {'Err':>4}  "
              f"{'Avg ms':>7}  {'Min':>6}  {'Max':>6}  {'σ':>6}")
    print(header)
    print(f"  {'─'*col}  {'─'*4}  {'─'*4}  {'─'*4}  {'─'*7}  {'─'*6}  {'─'*6}  {'─'*6}")

    for cmd, s in summary.items():
        avg = f"{s['rtt_avg_ms']:.1f}" if s["rtt_avg_ms"] is not None else "—"
        mn  = f"{s['rtt_min_ms']:.1f}" if s["rtt_min_ms"] is not None else "—"
        mx  = f"{s['rtt_max_ms']:.1f}" if s["rtt_max_ms"] is not None else "—"
        sd  = f"{s['rtt_stdev_ms']:.1f}" if s["rtt_stdev_ms"] is not None else "—"
        print(f"  {cmd:<{col}}  {s['ok']:>4}  {s['timeout']:>4}  "
              f"{s['error']:>4}  {avg:>7}  {mn:>6}  {mx:>6}  {sd:>6}")

    print()
    for cmd, s in summary.items():
        issues = s["type_issues"] + s["unknown_fields"] + s["notable_values"]
        if issues:
            print(f"  {cmd}:")
            for i in issues:
                print(f"    → {i}")
    print()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Marstek Venus E/C — API Behaviour Analyser",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("ip",
                        help="Device IP address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"UDP port (default: {DEFAULT_PORT})")
    parser.add_argument("--rounds", type=int, default=5,
                        help="Probe repetitions per command (default: 5)")
    parser.add_argument("--delay", type=float, default=4.0,
                        help="Delay between probes in seconds (default: 3.5 — below this the "
                             "device's ~3.3 s rate-limit causes systematic timeouts)")
    parser.add_argument("--raw", action="store_true",
                        help="Print raw request/response for each probe")
    parser.add_argument("--report", metavar="FILE",
                        help="Save full JSON report to FILE")
    parser.add_argument("--stress", action="store_true",
                        help="Stress mode: probe all commands back-to-back with minimal delay")
    parser.add_argument("--command", metavar="CMD",
                        help="Only probe a specific command id (e.g. Bat.GetStatus)")

    args = parser.parse_args()

    if args.stress:
        args.delay = 0.05   # intentionally below rate-limit — stress mode expects timeouts

    # Filter commands if --command given
    commands = COMMANDS
    if args.command:
        commands = [c for c in COMMANDS if c["id"] == args.command]
        if not commands:
            print(f"Unknown command '{args.command}'. Valid: "
                  + ", ".join(c["id"] for c in COMMANDS))
            return

    print(f"\nMarstek API Check  •  {args.ip}:{args.port}  •  "
          f"{datetime.now().strftime('%H:%M:%S')}")
    print(f"Rounds: {args.rounds}  •  Delay: {args.delay}s  •  "
          f"{'STRESS MODE' if args.stress else 'normal'}")
    print(SEP)

    all_records = []

    for cmd in commands:
        print(f"  Probing {cmd['id']} ", end="", flush=True)
        for i in range(args.rounds):
            r = probe(args.ip, args.port, cmd)
            all_records.append(r)

            # Progress indicator
            sym = "✓" if r["status"] == "ok" else ("T" if r["status"] == "timeout" else "✗")
            print(sym, end="", flush=True)

            if args.raw:
                print(f"\n    → {r['raw_request']}")
                print(f"    ← {r['raw_response']}")

            if i < args.rounds - 1:
                time.sleep(args.delay)

        print()  # newline after progress dots

    summary = summarise(all_records)
    print_summary(summary, args.rounds)

    # Save report
    if args.report:
        report = {
            "meta": {
                "tool":      "marstek_api_check",
                "device_ip": args.ip,
                "port":      args.port,
                "rounds":    args.rounds,
                "delay_s":   args.delay,
                "stress":    args.stress,
                "timestamp": datetime.now().isoformat(),
            },
            "summary": summary,
            "records": all_records,
        }
        with open(args.report, "w") as f:
            json.dump(report, f, indent=2)
        print(f"  Report saved → {args.report}")
        print()


if __name__ == "__main__":
    main()
