"""解析并执行路遥式桌面动作（Mac 可选）。"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


ACTION_OPEN_MEMO = re.compile(r"<<action:open_memo>>", re.I)
ACTION_MEMO_TEXT = re.compile(r"<<action:memo:([^>]+)>>", re.I)


def strip_action_tags(text: str) -> str:
    out = ACTION_OPEN_MEMO.sub("", text)
    out = ACTION_MEMO_TEXT.sub("", out)
    return out.strip()


def extract_actions(text: str) -> list[str]:
    actions: list[str] = []
    if ACTION_OPEN_MEMO.search(text):
        actions.append("open_memo")
    if ACTION_MEMO_TEXT.search(text):
        actions.append("memo_text")
    return actions


def run_actions(text: str) -> list[str]:
    """若 COMPANION_ACTIONS=1 且在 macOS，尝试执行白名单动作。"""
    if os.getenv("COMPANION_ACTIONS", "").strip() not in ("1", "true", "yes"):
        return []
    if os.uname().sysname != "Darwin":
        return []

    done: list[str] = []
    if ACTION_OPEN_MEMO.search(text):
        try:
            subprocess.run(
                ["osascript", "-e", 'tell application "Notes" to activate'],
                check=True,
                timeout=5,
            )
            done.append("open_memo")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            pass

    m = ACTION_MEMO_TEXT.search(text)
    if m:
        body = m.group(1).strip()
        if body:
            safe = body.replace('"', "'")[:500]
            script = (
                f'tell application "Notes" to make new note '
                f'at folder "Notes" with properties {{body:"{safe}"}}'
            )
            try:
                subprocess.run(["osascript", "-e", script], check=True, timeout=8)
                done.append("memo_text")
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
                pass
    return done


def apply_actions_to_reply(text: str, enabled: bool = False) -> tuple[str, list[str]]:
    actions = run_actions(text) if enabled else []
    return strip_action_tags(text), actions
