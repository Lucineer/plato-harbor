#!/usr/bin/env python3
"""PLATO Harbor — fleet coordination room. Agents post status, requests, and discoveries."""

import yaml, os
from pathlib import Path
from datetime import datetime, timezone
import fcntl

WORLD_DIR = Path(os.environ.get("WORLD_DIR", "world"))
MESSAGES_DIR = WORLD_DIR / "messages"
REQUESTS_DIR = WORLD_DIR / "requests"
STATUS_DIR = WORLD_DIR / "status"
COMMANDS_DIR = WORLD_DIR / "commands"
ROOMS_DIR = WORLD_DIR / "rooms"
LOGS_DIR = WORLD_DIR / "logs"
MAX_TURNS = 30
MAX_MESSAGES = 100

def log(level, msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{ts}] [{level}] {msg}", flush=True)

def atomic_write(path, data):
    tmp = str(path) + ".tmp"
    with open(tmp, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yaml.dump(data, f, default_flow_style=False)
        fcntl.flock(f, fcntl.LOCK_UN)
    os.replace(tmp, path)

def atomic_read(path):
    try:
        with open(path) as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            d = yaml.safe_load(f)
            fcntl.flock(f, fcntl.LOCK_UN)
            return d or {}
    except FileNotFoundError:
        return {}

def process_broadcast(cmd, agent):
    """Broadcast a message to the fleet."""
    msg = cmd.get("message", "")
    priority = cmd.get("priority", "normal")  # low, normal, high, critical
    tags = cmd.get("tags", [])
    if not msg:
        return {"passed": False, "error": "Empty message"}
    if len(msg) > 2000:
        return {"passed": False, "error": "Message too long (max 2000 chars)"}

    mid = f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}"
    message = {
        "id": mid, "from": agent, "message": msg,
        "priority": priority, "tags": tags,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write(MESSAGES_DIR / f"{mid}.yaml", message)

    # Trim old messages
    msgs = sorted(MESSAGES_DIR.glob("*.yaml"))
    if len(msgs) > MAX_MESSAGES:
        for old in msgs[:-MAX_MESSAGES]:
            old.unlink()

    log("INFO", f"Broadcast from {agent}: {msg[:80]}...")
    return {"passed": True, "message_id": mid}

def process_request(cmd, agent):
    """Post a request for fleet assistance."""
    title = cmd.get("title", "")
    description = cmd.get("description", "")
    needed_from = cmd.get("needed_from", [])  # specific agents
    urgency = cmd.get("urgency", "normal")

    if not title or not description:
        return {"passed": False, "error": "Title and description required"}

    rid = f"{agent}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    request = {
        "id": rid, "from": agent, "title": title,
        "description": description, "needed_from": needed_from,
        "urgency": urgency, "status": "open",
        "responses": [],
        "created": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write(REQUESTS_DIR / f"{rid}.yaml", request)
    log("INFO", f"Request from {agent}: {title}")
    return {"passed": True, "request_id": rid}

def process_checkin(cmd, agent):
    """Agent check-in with status."""
    status = cmd.get("status", "active")
    location = cmd.get("location", "unknown")
    working_on = cmd.get("working_on", "")
    capacity = cmd.get("capacity", "available")

    checkin = {
        "agent": agent, "status": status, "location": location,
        "working_on": working_on, "capacity": capacity,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write(STATUS_DIR / f"{agent}.yaml", checkin)

    room = atomic_read(ROOMS_DIR / "harbor.yaml")
    room.setdefault("checkins", {})
    room["checkins"][agent] = checkin["timestamp"]
    atomic_write(ROOMS_DIR / "harbor.yaml", room)

    log("INFO", f"Check-in: {agent} ({status}) at {location}")
    return {"passed": True}

def process_turns():
    for d in [COMMANDS_DIR, MESSAGES_DIR, REQUESTS_DIR, STATUS_DIR, ROOMS_DIR, LOGS_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    if not (ROOMS_DIR / "harbor.yaml").exists():
        atomic_write(ROOMS_DIR / "harbor.yaml", {"name": "PLATO Harbor", "checkins": {}})
    commands = sorted(COMMANDS_DIR.glob("*.yaml"))
    if not commands:
        return
    log("INFO", f"Processing {len(commands)} commands")
    counts = {}
    for cp in commands:
        cmd = atomic_read(cp)
        if not cmd:
            cp.unlink(); continue
        agent = cmd.get("agent", "unknown")
        counts[agent] = counts.get(agent, 0) + 1
        if counts[agent] > MAX_TURNS:
            cp.unlink(); continue
        action = cmd.get("action")
        if action == "broadcast":
            r = process_broadcast(cmd, agent)
        elif action == "request":
            r = process_request(cmd, agent)
        elif action == "checkin":
            r = process_checkin(cmd, agent)
        else:
            r = {"passed": False, "error": f"Unknown: {action}"}
        atomic_write(LOGS_DIR / f"turn-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}.yaml",
                     {"agent": agent, "action": action, "result": r,
                      "timestamp": datetime.now(timezone.utc).isoformat()})
        cp.unlink()
    log("INFO", f"Turn done")

if __name__ == "__main__":
    process_turns()
