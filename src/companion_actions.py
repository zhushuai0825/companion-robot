"""解析并执行路遥式桌面动作（Mac 本地 + 树莓派远程调用 Mac Agent）。"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path


ACTION_TAG = re.compile(r"<<action:([a-z_]+)(?::([^>]*))?>>", re.I)


def strip_action_tags(text: str) -> str:
    return ACTION_TAG.sub("", text).strip()


def extract_actions(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for m in ACTION_TAG.finditer(text):
        name = m.group(1).lower()
        arg = (m.group(2) or "").strip()
        out.append((name, arg))
    return out


def _run_osascript(script: str, timeout: int = 8) -> bool:
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=True,
            timeout=timeout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _mac_open_notes() -> bool:
    return _run_osascript('tell application "Notes" to activate')


def _mac_memo_text(body: str) -> bool:
    safe = body.replace('"', "'").replace("\\", "")[:500]
    script = (
        f'tell application "Notes" to make new note '
        f'at folder "Notes" with properties {{body:"{safe}"}}'
    )
    return _run_osascript(script)


def _mac_open_url(url: str) -> bool:
    if not url.startswith(("http://", "https://")):
        return False
    safe = url.replace('"', "")[:200]
    return _run_osascript(f'open location "{safe}"')


def _mac_set_clipboard(text: str) -> bool:
    safe = text.replace('"', "'")[:800]
    return _run_osascript(f'set the clipboard to "{safe}"')


def _mac_volume(level: str) -> bool:
    try:
        pct = int(level)
        pct = max(0, min(100, pct))
        subprocess.run(
            ["osascript", "-e", f"set volume output volume {pct}"],
            check=True,
            timeout=5,
        )
        return True
    except (ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def _remote_agent_url() -> str:
    return os.getenv("DESKTOP_AGENT_URL", "").strip().rstrip("/")


def _remote_call(action: str, arg: str = "") -> bool:
    url = _remote_agent_url()
    if not url:
        return False
    payload = json.dumps({"action": action, "arg": arg}).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/action",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    token = os.getenv("DESKTOP_AGENT_TOKEN", "").strip()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return bool(body.get("ok"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError):
        return False


def run_action(name: str, arg: str = "") -> bool:
    name = name.lower()
    on_mac = os.uname().sysname == "Darwin"

    if name == "open_memo":
        if on_mac:
            return _mac_open_notes()
        return _remote_call("open_memo")

    if name == "memo":
        if on_mac:
            return _mac_memo_text(arg)
        return _remote_call("memo", arg)

    if name == "open_url":
        if on_mac:
            return _mac_open_url(arg)
        return _remote_call("open_url", arg)

    if name == "clipboard":
        if on_mac:
            return _mac_set_clipboard(arg)
        return _remote_call("clipboard", arg)

    if name == "volume":
        if on_mac:
            return _mac_volume(arg)
        return _remote_call("volume", arg)

    if name == "notify":
        title = "路遥"
        body = arg[:120] if arg else "嗯，我在。"
        if on_mac:
            safe = body.replace('"', "'")
            return _run_osascript(
                f'display notification "{safe}" with title "{title}"'
            )
        return _remote_call("notify", arg)

    return False


def run_actions(text: str) -> list[str]:
    if os.getenv("COMPANION_ACTIONS", "").strip() not in ("1", "true", "yes"):
        cfg_enabled = os.getenv("COMPANION_ACTIONS_ENABLED", "")
        if cfg_enabled not in ("1", "true", "yes"):
            return []

    done: list[str] = []
    for name, arg in extract_actions(text):
        if run_action(name, arg):
            done.append(name)
    return done


def apply_actions_to_reply(text: str, enabled: bool = False) -> tuple[str, list[str]]:
    if not enabled and os.getenv("COMPANION_ACTIONS", "").strip() not in (
        "1",
        "true",
        "yes",
    ):
        return strip_action_tags(text), []
    actions = run_actions(text)
    return strip_action_tags(text), actions
