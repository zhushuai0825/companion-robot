"""长期记忆 v2：事实、开放情绪、约定、关系备注、会话摘要。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path


def default_memory() -> dict:
    return {
        "user_name": "",
        "mood_note": "",
        "facts": [],
        "open_loops": [],
        "promises": [],
        "relationship_notes": "",
        "session_summaries": [],
        "turn_count": 0,
        "last_seen": "",
    }


class CompanionMemory:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return default_memory()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return default_memory()
        base = default_memory()
        for key in base:
            if key in raw:
                base[key] = raw[key]
        if isinstance(raw.get("facts"), list):
            base["facts"] = [str(x).strip() for x in raw["facts"] if str(x).strip()]
        if isinstance(raw.get("open_loops"), list):
            base["open_loops"] = [
                x for x in raw["open_loops"] if isinstance(x, dict) and x.get("summary")
            ]
        if isinstance(raw.get("promises"), list):
            base["promises"] = [
                x for x in raw["promises"] if isinstance(x, dict) and x.get("text")
            ]
        if isinstance(raw.get("session_summaries"), list):
            base["session_summaries"] = [
                x for x in raw["session_summaries"] if isinstance(x, dict) and x.get("summary")
            ]
        return base

    def save(self) -> None:
        self.data["last_seen"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def bump_turn(self) -> int:
        self.data["turn_count"] = int(self.data.get("turn_count", 0)) + 1
        return self.data["turn_count"]

    def context_block(self) -> str:
        parts: list[str] = []
        if self.data.get("user_name"):
            parts.append(f"用户昵称：{self.data['user_name']}")
        if self.data.get("mood_note"):
            parts.append(
                f"最近情绪（可自然提起，像惦记）：{self.data['mood_note']}"
            )
        facts = self.data.get("facts") or []
        if facts:
            parts.append("长期事实（挑一条自然提起）：" + "；".join(facts[-8:]))
        loops = [x for x in (self.data.get("open_loops") or []) if x.get("status") == "open"]
        if loops:
            loop_text = "；".join(x["summary"][:60] for x in loops[-3:])
            parts.append(f"未完成的心事（可回访一句）：{loop_text}")
        promises = self.data.get("promises") or []
        if promises:
            prom_text = "；".join(
                f"{x.get('text', '')[:40]}"
                for x in promises[-3:]
            )
            parts.append(f"你说过的约定（可轻轻提起）：{prom_text}")
        if self.data.get("relationship_notes"):
            parts.append(f"相处备注：{self.data['relationship_notes'][:120]}")
        summaries = self.data.get("session_summaries") or []
        if summaries:
            last = summaries[-1]
            parts.append(f"上次聊了什么（背景）：{last.get('summary', '')[:100]}")
        if self.data.get("last_seen"):
            parts.append(f"上次见面：{self.data['last_seen']}")
        return "\n".join(parts)

    def apply_updates(
        self,
        updates: dict,
        max_facts: int = 30,
        max_open_loops: int = 10,
        max_summaries: int = 12,
    ) -> None:
        if not updates:
            return
        name = str(updates.get("user_name", "")).strip()
        if name:
            self.data["user_name"] = name[:32]
        mood = str(updates.get("mood_note", "")).strip()
        if mood:
            self.data["mood_note"] = mood[:120]
        rel = str(updates.get("relationship_note", "")).strip()
        if rel:
            self.data["relationship_notes"] = rel[:200]
        new_facts = updates.get("new_facts") or []
        if isinstance(new_facts, list):
            for item in new_facts:
                text = str(item).strip()
                if not text or text in self.data["facts"]:
                    continue
                self.data["facts"].append(text[:80])
        self.data["facts"] = self.data["facts"][-max_facts:]

        for item in updates.get("open_loops_add") or []:
            if not isinstance(item, dict):
                continue
            summary = str(item.get("summary", "")).strip()
            if not summary:
                continue
            self.data["open_loops"].append(
                {
                    "id": str(item.get("id") or uuid.uuid4().hex[:8]),
                    "summary": summary[:80],
                    "status": "open",
                    "created_at": datetime.now().strftime("%Y-%m-%d"),
                }
            )
        close_keys = updates.get("open_loops_close") or []
        if isinstance(close_keys, list):
            for key in close_keys:
                key = str(key).strip()
                for loop in self.data["open_loops"]:
                    if loop.get("status") != "open":
                        continue
                    if key in loop.get("id", "") or key in loop.get("summary", ""):
                        loop["status"] = "closed"
        self.data["open_loops"] = self.data["open_loops"][-max_open_loops:]

        for item in updates.get("promises_add") or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            self.data["promises"].append(
                {
                    "id": str(item.get("id") or uuid.uuid4().hex[:8]),
                    "text": text[:80],
                    "due_hint": str(item.get("due_hint", ""))[:40],
                    "created_at": datetime.now().strftime("%Y-%m-%d"),
                }
            )
        self.data["promises"] = self.data["promises"][-10:]

        summary = str(updates.get("session_summary", "")).strip()
        if summary:
            self.data["session_summaries"].append(
                {
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "summary": summary[:200],
                }
            )
            self.data["session_summaries"] = self.data["session_summaries"][-max_summaries:]

    def pick_opening_hook(self) -> str | None:
        loops = [x for x in (self.data.get("open_loops") or []) if x.get("status") == "open"]
        if loops:
            return loops[-1]["summary"]
        promises = self.data.get("promises") or []
        if promises:
            return promises[-1].get("text")
        if self.data.get("mood_note"):
            return self.data["mood_note"]
        return None
