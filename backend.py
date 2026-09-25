#!/usr/bin/env python3
"""User-owned controls for the Omarchy notification rules bar plugin.

This helper never replaces org.freedesktop.Notifications. It manages the
crash-watcher's supported environment, Omarchy's DND IPC, and a journal-backed
crash inbox. All subprocess calls use argv, never shell evaluation.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any


COREDUMP_MESSAGE_ID = "fc2e22bc6ee647b6b90729ab34a250b1"
PLUGIN_ID = "andean-bridge.notification-rules-mgr"
DROPIN_NAME = "50-omarchy-notification-rules-mgr.conf"
PROFILE_NAMES = ("Normal", "Focus", "Presenting", "Debugging")
MAX_RULES = 100
MAX_JOURNAL_ROWS = 250


def default_config() -> dict[str, Any]:
    return {
        "version": 1,
        "activeProfile": "Normal",
        "dndManaged": False,
        "manualDnd": None,
        "dedupeSeconds": 60,
        "profiles": {
            "Normal": {"dnd": False, "muteAllCrashes": False},
            "Focus": {"dnd": True, "muteAllCrashes": False},
            "Presenting": {"dnd": True, "muteAllCrashes": True},
            "Debugging": {"dnd": False, "muteAllCrashes": False},
        },
        "rules": [],
        "quietHours": {
            "enabled": False,
            "start": "22:00",
            "end": "08:00",
            "dnd": True,
            "muteCrashes": True,
            "digest": True,
        },
    }


def default_state() -> dict[str, Any]:
    return {"version": 1, "quietActive": False, "quietStartedAt": None, "preQuietDnd": None}


def config_base() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def state_base() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")


def paths() -> dict[str, Path]:
    base = config_base()
    return {
        "config": base / "omarchy" / "notification-rules-mgr.json",
        "state": state_base() / "omarchy" / "notification-rules-mgr.json",
        "dropin": base / "systemd/user/omarchy-crash-watch.service.d" / DROPIN_NAME,
        "capture_off": state_base() / "omarchy/toggles/crash-capture-off",
        "history": state_base() / "omarchy/notifications/history",
        "popups": state_base() / "omarchy/notifications",
    }


def read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return copy.deepcopy(fallback)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Invalid object in {path}")
    merged = copy.deepcopy(fallback)
    merged.update(value)
    if isinstance(fallback.get("quietHours"), dict):
        quiet = value.get("quietHours")
        if quiet is not None and not isinstance(quiet, dict):
            raise ValueError(f"Invalid quiet hours in {path}")
        merged["quietHours"] = {**fallback["quietHours"], **(quiet or {})}
    if isinstance(fallback.get("profiles"), dict):
        profiles = value.get("profiles")
        if profiles is not None and not isinstance(profiles, dict):
            raise ValueError(f"Invalid profiles in {path}")
        merged["profiles"] = copy.deepcopy(fallback["profiles"])
        for name, profile in (profiles or {}).items():
            if name in PROFILE_NAMES and isinstance(profile, dict):
                merged["profiles"][name].update(profile)
    return merged


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".notification-rules-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            os.fchmod(output.fileno(), 0o600)
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_unit_override(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".notification-rules-unit-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            os.fchmod(output.fileno(), 0o644)
            output.write(value)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run(argv: list[str], *, timeout: int = 8) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)


def normalize_process(value: str) -> str:
    name = Path(str(value).strip()).name
    if not name or len(name) > 120 or any(c in name for c in "\r\n\0%"):
        raise ValueError("Enter a process name without line breaks or percent signs")
    return name


def bash_ere_literal(value: str) -> str:
    metacharacters = r".\^$*+?{}[]|()"
    return "".join("\\" + char if char in metacharacters else char for char in value)


def rule_expiry(duration: str, now: dt.datetime) -> tuple[int | None, bool]:
    if duration == "hour":
        return int((now + dt.timedelta(hours=1)).timestamp()), False
    if duration == "eight_hours":
        return int((now + dt.timedelta(hours=8)).timestamp()), False
    if duration == "seven_days":
        return int((now + dt.timedelta(days=7)).timestamp()), False
    if duration == "tomorrow":
        tomorrow = (now + dt.timedelta(days=1)).date()
        return int(dt.datetime.combine(tomorrow, dt.time(hour=9), now.tzinfo).timestamp()), False
    if duration == "session":
        return None, True
    if duration == "forever":
        return None, False
    raise ValueError("Choose one hour, eight hours, seven days, tomorrow, this debugging session, or always")


def active_rules(config: dict[str, Any], now: dt.datetime) -> list[dict[str, Any]]:
    timestamp = int(now.timestamp())
    profile = config.get("activeProfile", "Normal")
    return [
        rule for rule in config.get("rules", [])
        if rule.get("profile") in ("All", profile)
        and (rule.get("expiresAt") is None or int(rule["expiresAt"]) > timestamp)
    ]


def quiet_active(config: dict[str, Any], now: dt.datetime) -> bool:
    quiet = config.get("quietHours") or {}
    if not quiet.get("enabled"):
        return False
    try:
        start = dt.time.fromisoformat(quiet["start"])
        end = dt.time.fromisoformat(quiet["end"])
    except (KeyError, TypeError, ValueError):
        return False
    current = now.time().replace(tzinfo=None)
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end


def ignored_processes(config: dict[str, Any], now: dt.datetime) -> tuple[bool, list[str]]:
    profile = config["profiles"].get(config.get("activeProfile"), {})
    quiet = config["quietHours"]
    all_crashes = bool(profile.get("muteAllCrashes")) or (
        quiet_active(config, now) and bool(quiet.get("muteCrashes"))
    )
    names = sorted({
        normalize_process(rule["process"])
        for rule in active_rules(config, now)
        if rule.get("action") == "silence"
    }, key=str.casefold)
    return all_crashes, names


def effective_pattern(config: dict[str, Any], now: dt.datetime) -> str:
    all_crashes, names = ignored_processes(config, now)
    if all_crashes:
        return ".*"
    if not names:
        return ""
    return "^(" + "|".join(bash_ere_literal(name) for name in names) + ")$"


def effective_dnd(config: dict[str, Any], now: dt.datetime) -> bool | None:
    if quiet_active(config, now) and config["quietHours"].get("dnd"):
        return True
    if not config.get("dndManaged"):
        return None
    if config.get("manualDnd") is not None:
        return bool(config["manualDnd"])
    profile = config["profiles"].get(config.get("activeProfile"), {})
    return bool(profile.get("dnd"))


def systemd_quoted(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def dropin_text(pattern: str, dedupe_seconds: int) -> str | None:
    lines: list[str] = []
    if pattern:
        lines.append(f'Environment="OMARCHY_CRASH_IGNORE={systemd_quoted(pattern)}"')
    if dedupe_seconds != 60:
        lines.append(f'Environment="OMARCHY_CRASH_DEDUPE_SECONDS={dedupe_seconds}"')
    if not lines:
        return None
    return "# Managed by Omarchy Notification Rules Manager.\n[Service]\n" + "\n".join(lines) + "\n"


def external_ignore_conflicts(dropin: Path) -> list[str]:
    unit = "omarchy-crash-watch.service"
    candidates = [
        Path("/usr/lib/systemd/user") / unit,
        Path("/etc/systemd/user") / unit,
    ]
    for directory in (
        Path("/usr/lib/systemd/user") / f"{unit}.d",
        Path("/etc/systemd/user") / f"{unit}.d",
        dropin.parent,
    ):
        if directory.is_dir():
            candidates.extend(directory.glob("*.conf"))
    conflicts = []
    for path in candidates:
        if path == dropin:
            continue
        try:
            if "OMARCHY_CRASH_IGNORE" in path.read_text(encoding="utf-8"):
                conflicts.append(str(path))
        except OSError:
            continue
    return conflicts


def apply_crash_settings(config: dict[str, Any], location: dict[str, Path], now: dt.datetime) -> bool:
    target = location["dropin"]
    desired = dropin_text(effective_pattern(config, now), int(config["dedupeSeconds"]))
    previous = target.read_text(encoding="utf-8") if target.exists() else None
    if desired == previous:
        return False
    if desired and external_ignore_conflicts(target):
        raise RuntimeError("Another crash-watch override sets OMARCHY_CRASH_IGNORE; review it before enabling plugin rules")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        if desired is None:
            target.unlink(missing_ok=True)
        else:
            write_unit_override(target, desired)
        reload_result = run(["systemctl", "--user", "daemon-reload"])
        if reload_result.returncode != 0:
            raise RuntimeError(reload_result.stderr.strip() or "Could not reload user services")
        if not location["capture_off"].exists():
            restart = run(["systemctl", "--user", "try-restart", "omarchy-crash-watch.service"])
            if restart.returncode != 0:
                raise RuntimeError(restart.stderr.strip() or "Could not restart crash watcher")
    except Exception:
        if previous is None:
            target.unlink(missing_ok=True)
        else:
            write_unit_override(target, previous)
        run(["systemctl", "--user", "daemon-reload"])
        raise
    return True


def apply_dnd(config: dict[str, Any], now: dt.datetime) -> str | None:
    wanted = effective_dnd(config, now)
    if wanted is None:
        return None
    return set_dnd(wanted)


def set_dnd(wanted: bool) -> str | None:
    result = run(["omarchy-shell", "notifications", "setDnd", "on" if wanted else "off"])
    if result.returncode != 0:
        return result.stderr.strip() or "Could not change Do Not Disturb"
    return None


def dnd_state() -> bool | None:
    result = run(["omarchy-shell", "notifications", "dndState"])
    if result.returncode:
        return None
    value = result.stdout.strip().lower()
    return True if value == "on" else False if value == "off" else None


def journal_rows(*, since: int | None = None, limit: int = MAX_JOURNAL_ROWS) -> list[dict[str, Any]]:
    argv = ["journalctl", "--no-pager", "-o", "json", f"MESSAGE_ID={COREDUMP_MESSAGE_ID}"]
    if since is not None:
        argv.append(f"--since=@{since}")
    else:
        argv.extend(["-n", str(limit)])
    result = run(argv, timeout=15)
    if result.returncode:
        return []
    rows = []
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
            if str(item.get("_UID", "")) != str(os.getuid()):
                continue
            executable = str(item.get("COREDUMP_EXE") or "")
            name = Path(executable).name if executable.startswith("/") else str(item.get("COREDUMP_COMM") or "")
            if not name:
                continue
            timestamp = int(item.get("__REALTIME_TIMESTAMP", 0)) // 1_000_000
            rows.append({
                "name": name,
                "executable": executable,
                "pid": str(item.get("COREDUMP_PID") or ""),
                "signal": str(item.get("COREDUMP_SIGNAL_NAME") or ""),
                "timestamp": timestamp,
            })
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
    return sorted(rows, key=lambda row: row["timestamp"], reverse=True)


def recent_notifications(location: dict[str, Path]) -> list[dict[str, Any]]:
    rows = []
    for directory in (location["popups"], location["history"]):
        try:
            files = list(directory.glob("*.json"))
        except OSError:
            continue
        for path in files:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                app = str(item.get("app") or "Unknown app")
                summary = str(item.get("summary") or "Untitled alert")
                crash_process = ""
                if app == "omarchy-action" and summary.startswith("Process crashed: "):
                    try:
                        crash_process = normalize_process(summary.removeprefix("Process crashed: "))
                    except ValueError:
                        pass
                rows.append({
                    "app": app,
                    "summary": summary,
                    "body": str(item.get("body") or ""),
                    "timestamp": int(item.get("timestamp") or 0) // 1000,
                    "onScreen": directory == location["popups"],
                    "crashProcess": crash_process,
                })
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
    unique = {(row["app"], row["summary"], row["timestamp"]): row for row in rows}
    return sorted(unique.values(), key=lambda row: row["timestamp"], reverse=True)[:20]


def classify_crash(name: str, config: dict[str, Any], now: dt.datetime) -> str:
    all_crashes, ignored = ignored_processes(config, now)
    if all_crashes:
        return "muted by profile"
    if name in ignored:
        return "muted by rule"
    return "allowed"


def group_crashes(rows: list[dict[str, Any]], config: dict[str, Any], now: dt.datetime) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = row["name"]
        if name not in grouped:
            grouped[name] = {**row, "count": 0, "policy": classify_crash(name, config, now)}
        grouped[name]["count"] += 1
    return sorted(grouped.values(), key=lambda row: row["timestamp"], reverse=True)


def snapshot(config: dict[str, Any], state: dict[str, Any], location: dict[str, Path], now: dt.datetime) -> dict[str, Any]:
    crashes = journal_rows()
    notifications = recent_notifications(location)
    for row in notifications:
        if row["crashProcess"]:
            row["policy"] = classify_crash(row["crashProcess"], config, now)
    return {
        "ok": True,
        "config": config,
        "quietActive": quiet_active(config, now),
        "effectiveDnd": dnd_state(),
        "effectivePattern": effective_pattern(config, now),
        "captureEnabled": not location["capture_off"].exists(),
        "crashes": group_crashes(crashes, config, now),
        "crashEvents": crashes[:60],
        "notifications": notifications,
        "status": state.get("status") or "",
        "now": int(now.timestamp()),
    }


def expire_rules(config: dict[str, Any], now: dt.datetime) -> bool:
    before = len(config["rules"])
    timestamp = int(now.timestamp())
    config["rules"] = [
        rule for rule in config["rules"]
        if rule.get("expiresAt") is None or int(rule["expiresAt"]) > timestamp
    ]
    return len(config["rules"]) != before


def send_crash_digest(start: int, end: int) -> str:
    rows = [row for row in journal_rows(since=start, limit=0) if row["timestamp"] < end]
    if not rows:
        return "No crashes during quiet hours"
    grouped: dict[str, int] = {}
    for row in rows:
        grouped[row["name"]] = grouped.get(row["name"], 0) + 1
    top = sorted(grouped.items(), key=lambda item: (-item[1], item[0]))[:3]
    detail = ", ".join(f"{name} ×{count}" for name, count in top)
    if len(grouped) > len(top):
        detail += f" and {len(grouped) - len(top)} more"
    run(["omarchy-notification-send", "--urgency", "low", "Crash digest", f"{len(rows)} crashes: {detail}"])
    return f"Quiet hours ended · {len(rows)} crashes summarized"


def reconcile(config: dict[str, Any], state: dict[str, Any], location: dict[str, Path], now: dt.datetime) -> str | None:
    changed = expire_rules(config, now)
    is_quiet = quiet_active(config, now)
    was_quiet = bool(state.get("quietActive"))
    if is_quiet and not was_quiet:
        state["quietStartedAt"] = int(now.timestamp())
        if config["quietHours"].get("dnd"):
            state["preQuietDnd"] = dnd_state()
    elif was_quiet and not is_quiet:
        started = int(state.get("quietStartedAt") or now.timestamp())
        if config["quietHours"].get("digest"):
            state["status"] = send_crash_digest(started, int(now.timestamp()))
        state["quietStartedAt"] = None
    state["quietActive"] = is_quiet
    applied = apply_crash_settings(config, location, now)
    dnd_warning = apply_dnd(config, now)
    if was_quiet and not is_quiet and effective_dnd(config, now) is None and state.get("preQuietDnd") is not None:
        dnd_warning = set_dnd(bool(state["preQuietDnd"]))
    if was_quiet and not is_quiet:
        state["preQuietDnd"] = None
    if dnd_warning:
        state["status"] = dnd_warning
    elif applied:
        state["status"] = "Crash watcher updated"
    if changed:
        write_json(location["config"], config)
    write_json(location["state"], state)
    return dnd_warning


def mutate(config: dict[str, Any], action: str, args: list[str], now: dt.datetime) -> str:
    if action == "add":
        if len(args) < 3:
            raise ValueError("Usage: add PROCESS ACTION DURATION [PROFILE]")
        process = normalize_process(args[0])
        rule_action, duration = args[1], args[2]
        profile = args[3] if len(args) > 3 else "All"
        if rule_action != "silence":
            raise ValueError("Crash rules support silence only")
        if profile not in ("All", *PROFILE_NAMES):
            raise ValueError("Unknown profile")
        if len(config["rules"]) >= MAX_RULES:
            raise ValueError("Rule limit reached")
        expires_at, until_session_end = rule_expiry(duration, now)
        if until_session_end and config["activeProfile"] != "Debugging":
            raise ValueError("Start the Debugging profile for a session mute")
        config["rules"] = [
            rule for rule in config["rules"]
            if not (rule.get("process") == process and rule.get("profile") == profile)
        ]
        config["rules"].insert(0, {
            "id": uuid.uuid4().hex[:12],
            "process": process,
            "action": rule_action,
            "profile": profile,
            "expiresAt": expires_at,
            "untilSessionEnd": until_session_end,
            "createdAt": int(now.timestamp()),
        })
        return f"{process} {rule_action} rule saved"
    if action == "remove":
        if not args:
            raise ValueError("Rule id required")
        before = len(config["rules"])
        config["rules"] = [rule for rule in config["rules"] if rule.get("id") != args[0]]
        if len(config["rules"]) == before:
            raise ValueError("Rule was not found")
        return "Rule removed"
    if action == "profile":
        if not args or args[0] not in PROFILE_NAMES:
            raise ValueError("Unknown profile")
        if config["activeProfile"] == "Debugging" and args[0] != "Debugging":
            config["rules"] = [rule for rule in config["rules"] if not rule.get("untilSessionEnd")]
        config["activeProfile"] = args[0]
        config["dndManaged"] = True
        config["manualDnd"] = None
        return f"{args[0]} profile active"
    if action == "dnd":
        if not args or args[0] not in ("on", "off"):
            raise ValueError("DND value must be on or off")
        config["dndManaged"] = True
        config["manualDnd"] = args[0] == "on"
        return "Do Not Disturb " + args[0]
    if action == "quiet":
        if len(args) != 4:
            raise ValueError("Usage: quiet ENABLED START END DIGEST")
        enabled = args[0] == "on"
        for value in args[1:3]:
            if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
                raise ValueError("Use 24-hour times such as 22:00")
        if args[1] == args[2]:
            raise ValueError("Quiet hours need different start and end times")
        if args[0] not in ("on", "off") or args[3] not in ("on", "off"):
            raise ValueError("Quiet hours and digest values must be on or off")
        config["quietHours"].update({
            "enabled": enabled, "start": args[1], "end": args[2], "digest": args[3] == "on"
        })
        return "Quiet hours " + ("enabled" if enabled else "disabled")
    if action == "dedupe":
        if not args or not args[0].isdigit() or not 10 <= int(args[0]) <= 3600:
            raise ValueError("Choose 10–3600 seconds")
        config["dedupeSeconds"] = int(args[0])
        return "Crash repeat window updated"
    raise ValueError("Unknown action")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("read", "tick", "add", "remove", "profile", "dnd", "quiet", "dedupe", "capture", "dismiss", "clear", "replay"))
    parser.add_argument("args", nargs="*")
    request = parser.parse_args(argv)
    location = paths()
    now = dt.datetime.now().astimezone()
    try:
        config = read_json(location["config"], default_config())
        state = read_json(location["state"], default_state())
        if request.action in ("read", "tick"):
            if request.action == "tick":
                reconcile(config, state, location, now)
        elif request.action == "capture":
            desired = request.args[0] if request.args else ""
            if desired not in ("on", "off"):
                raise ValueError("Capture value must be on or off")
            current = not location["capture_off"].exists()
            if current != (desired == "on"):
                result = run(["omarchy", "toggle", "crash-capture"])
                if result.returncode:
                    raise RuntimeError(result.stderr.strip() or "Could not toggle crash capture")
            state["status"] = "Crash alerts " + desired
            write_json(location["state"], state)
        elif request.action in ("dismiss", "clear", "replay"):
            ipc_name = {"dismiss": "dismissAll", "clear": "clear", "replay": "showHistory"}[request.action]
            ipc = ["omarchy-shell", "notifications", ipc_name]
            result = run(ipc)
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or "Notification command failed")
            state["status"] = {"dismiss": "Visible alerts dismissed", "clear": "Recent history cleared", "replay": "Recent history shown"}[request.action]
            write_json(location["state"], state)
        else:
            message = mutate(config, request.action, request.args, now)
            warning = reconcile(config, state, location, now)
            write_json(location["config"], config)
            state["status"] = message if not warning else message + " · " + warning
            write_json(location["state"], state)
        print(json.dumps(snapshot(config, state, location, now), ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
