"""陪伴对话核心：固定全局人设 + 长期记忆 + 情绪标签。"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from companion_memory import CompanionMemory
from companion_actions import apply_actions_to_reply
from companion_persona import (
    BANNED_PHRASES,
    CANON_EXPAND_POLISH,
    COMPRESS_POLISH,
    POLISH_SYSTEM,
    build_system_prompt,
    has_formula_mismatch,
    is_literary_reply,
    is_weak_companion_reply,
    length_hint_for,
    load_companion_config,
    max_chars_for,
    max_tokens_for,
    min_chars_for,
    parse_reply_and_emotion,
    pick_opening,
)

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent

load_dotenv(SRC / ".env")
load_dotenv(ROOT / ".env")

API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()

MEMORY_EXTRACT_PROMPT = """从下面一轮对话中提取长期记忆，只输出 JSON，不要其它文字。
格式：
{
  "user_name": "",
  "mood_note": "",
  "new_facts": [],
  "open_loops_add": [{"summary": "未完成情绪或话题，简短"}],
  "open_loops_close": ["要关闭的 open_loop 摘要关键词"],
  "promises_add": [{"text": "约定内容", "due_hint": "时间提示可空"}],
  "relationship_note": ""
}
规则：
- user_name：仅用户明确自称/昵称时填写
- mood_note：当前情绪或近况一句话
- new_facts：可长期记住的事实（工作、家人、爱好、烦恼），简短
- open_loops_add：用户透露但未消化完的情绪/话题（吵架、失眠、委屈等）
- open_loops_close：用户明确说「没事了」「解决了」时，用摘要关键词关闭
- promises_add：用户说「明天要说」「周五要」等约定
- relationship_note：相处偏好（讨厌加油、喜欢短句等），有则更新
不要记琐碎寒暄、不要重复已有内容。"""

SESSION_SUMMARY_PROMPT = """用一句话概括这段对话发生了什么（情绪与话题），供下次见面时背景回忆。
不超过 40 字，不要列表，不要 JSON。"""


@dataclass(frozen=True)
class ChatResult:
    text: str
    emotion: str = "neutral"


def _strip_robotic(text: str) -> str:
    out = text.strip()
    for phrase in BANNED_PHRASES:
        out = out.replace(phrase, "")
    out = re.sub(r"^[①②③④⑤\d]+[.、)]\s*", "", out)
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out or text.strip()


def _cleanup_reply(text: str) -> str:
    out = _strip_robotic(text)
    out = re.sub(r"[（(][^）)]*[）)]", "", out)
    out = re.sub(r"[，,、]\s*[。．.]$", "。", out)
    out = re.sub(r"[，,、]+$", "……", out)
    out = re.sub(r"[。．.]{2,}", "。", out)
    out = re.sub(r"……{3,}", "……", out)
    if re.search(r"[，,、…]$", out) and len(out) < 8:
        out = out.rstrip("，,、…") + "……"
    return out.strip()


class CompanionBrain:
    def __init__(self, config_path: Path | None = None) -> None:
        if not API_KEY:
            raise SystemExit("缺少 DEEPSEEK_API_KEY：请在 companion-robot/src/.env 里配置")
        self.cfg = load_companion_config(config_path)
        speaking = self.cfg.get("speaking") or {}
        self.temperature = float(speaking.get("temperature", 0.9))
        self.polish = bool(speaking.get("polish", True))
        self.polish_always = bool(speaking.get("polish_always", True))
        self.max_tokens = int(speaking.get("max_tokens", 280))

        mem_cfg = self.cfg.get("memory") or {}
        mem_rel = mem_cfg.get("file", "data/companion_memory.json")
        self.memory = CompanionMemory(ROOT / mem_rel)
        self.max_facts = int(mem_cfg.get("max_facts", 30))
        self.max_open_loops = int(mem_cfg.get("max_open_loops", 10))
        self.summarize_every = int(mem_cfg.get("summarize_every", 8))
        self.actions_enabled = bool((self.cfg.get("actions") or {}).get("enabled", False))

        self.client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
        self._rebuild_messages()

    def _rebuild_messages(self) -> None:
        self.messages = [
            {
                "role": "system",
                "content": build_system_prompt(
                    self.cfg, self.memory.context_block(), length_hint_for("")
                ),
            }
        ]

    def refresh_system(self, user_text: str = "") -> None:
        hint = length_hint_for(user_text) if user_text else ""
        self.messages[0] = {
            "role": "system",
            "content": build_system_prompt(
                self.cfg, self.memory.context_block(), hint
            ),
        }

    def chat(self, user_text: str) -> ChatResult:
        self.refresh_system(user_text)
        self.messages.append({"role": "user", "content": user_text})
        resp = self.client.chat.completions.create(
            model=MODEL,
            messages=self.messages,
            temperature=self.temperature,
            top_p=0.92,
            max_tokens=max_tokens_for(user_text, self.max_tokens),
        )
        raw = (resp.choices[0].message.content or "").strip()
        polished = self._polish_if_needed(user_text, raw)
        polished, _actions = apply_actions_to_reply(polished, self.actions_enabled)
        text, emotion = parse_reply_and_emotion(polished)
        text = _cleanup_reply(text)
        if (
            len(text) > max_chars_for(user_text)
            or is_literary_reply(text)
            or has_formula_mismatch(user_text, text)
        ):
            compressed = self._compress_if_needed(user_text, text, emotion)
            text, emotion = parse_reply_and_emotion(compressed)
            text = _cleanup_reply(text)
        if has_formula_mismatch(user_text, text):
            text = self._fix_formula_mismatch(user_text, text, emotion)
            text, emotion = parse_reply_and_emotion(text)
            text = _cleanup_reply(text)
        if len(text) < min_chars_for(user_text):
            expanded = self._expand_canon_if_needed(user_text, text, emotion)
            text, emotion = parse_reply_and_emotion(expanded)
            text = _cleanup_reply(text)
        self.messages.append({"role": "assistant", "content": f"{text}\n<<emotion:{emotion}>>"})
        self.memory.bump_turn()
        self._maybe_remember(user_text, text)
        if self.summarize_every > 0 and self.memory.data["turn_count"] % self.summarize_every == 0:
            self._maybe_summarize_session()
        return ChatResult(text=text, emotion=emotion)

    def _polish_if_needed(self, user_text: str, draft: str) -> str:
        if not self.polish or not draft:
            return draft
        weak = is_weak_companion_reply(draft)
        literary = is_literary_reply(draft)
        formula = has_formula_mismatch(user_text, draft)
        if not self.polish_always and not weak and not literary and not formula and len(draft) <= 72:
            return draft
        try:
            resp = self.client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": POLISH_SYSTEM},
                    {
                        "role": "user",
                        "content": f"用户刚说：{user_text}\n\n待润色：{draft}",
                    },
                ],
                temperature=0.72,
                max_tokens=max_tokens_for(user_text, self.max_tokens),
            )
            polished = (resp.choices[0].message.content or "").strip()
            return polished or draft
        except Exception:
            return draft

    def _compress_if_needed(self, user_text: str, text: str, emotion: str) -> str:
        limit = max_chars_for(user_text)
        if len(text) <= limit and not is_literary_reply(text):
            return text
        try:
            resp = self.client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": COMPRESS_POLISH},
                    {
                        "role": "user",
                        "content": (
                            f"字数上限：{limit}\n用户说：{user_text}\n\n待压缩："
                            f"{text}\n<<emotion:{emotion}>>"
                        ),
                    },
                ],
                temperature=0.65,
                max_tokens=max_tokens_for(user_text, self.max_tokens),
            )
            out = (resp.choices[0].message.content or "").strip()
            return out or f"{text}\n<<emotion:{emotion}>>"
        except Exception:
            return f"{text[:limit]}\n<<emotion:{emotion}>>"

    def _fix_formula_mismatch(self, user_text: str, text: str, emotion: str) -> str:
        try:
            resp = self.client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": POLISH_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"用户刚说：{user_text}\n\n"
                            "下面回复套了不该套的公式（摸不到额头/前三条/编造天气/替用户说我到家了）。"
                            "请改写成自然路遥口吻，删掉套话，保留陪伴感：\n"
                            f"{text}\n<<emotion:{emotion}>>"
                        ),
                    },
                ],
                temperature=0.68,
                max_tokens=max_tokens_for(user_text, self.max_tokens),
            )
            out = (resp.choices[0].message.content or "").strip()
            return out or f"{text}\n<<emotion:{emotion}>>"
        except Exception:
            return f"{text}\n<<emotion:{emotion}>>"

    def _expand_canon_if_needed(self, user_text: str, text: str, emotion: str) -> str:
        try:
            resp = self.client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": CANON_EXPAND_POLISH},
                    {
                        "role": "user",
                        "content": (
                            f"用户说：{user_text}\n\n"
                            f"当前回复仅{len(text)}字，太短。请扩写：\n"
                            f"{text}\n<<emotion:{emotion}>>"
                        ),
                    },
                ],
                temperature=0.78,
                max_tokens=max_tokens_for(user_text, self.max_tokens),
            )
            out = (resp.choices[0].message.content or "").strip()
            return out or f"{text}\n<<emotion:{emotion}>>"
        except Exception:
            return f"{text}\n<<emotion:{emotion}>>"

    def _maybe_remember(self, user_text: str, reply: str) -> None:
        triggers = (
            "我叫", "我是", "名字", "难过", "开心", "孤独", "压力", "焦虑",
            "喜欢", "讨厌", "工作", "上班", "学校", "累", "烦", "郁闷",
            "昨天", "上次", "记得", "约定", "明天", "失眠", "吵架", "气",
        )
        if not any(t in user_text for t in triggers):
            return
        try:
            raw = self.client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": MEMORY_EXTRACT_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"已有记忆：\n{self.memory.context_block()}\n\n"
                            f"用户：{user_text}\n助手：{reply}"
                        ),
                    },
                ],
                temperature=0.2,
            )
            text = (raw.choices[0].message.content or "").strip()
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
            updates = json.loads(text)
            self.memory.apply_updates(
                updates,
                max_facts=self.max_facts,
                max_open_loops=self.max_open_loops,
            )
            self.memory.save()
            self.refresh_system(user_text)
        except (json.JSONDecodeError, Exception):
            pass

    def _maybe_summarize_session(self) -> None:
        if len(self.messages) < 4:
            return
        try:
            recent = self.messages[-min(10, len(self.messages)) :]
            dialog = []
            for m in recent:
                if m["role"] == "user":
                    dialog.append(f"用户：{m['content']}")
                elif m["role"] == "assistant":
                    visible, _ = parse_reply_and_emotion(m["content"])
                    dialog.append(f"路遥：{visible}")
            raw = self.client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SESSION_SUMMARY_PROMPT},
                    {"role": "user", "content": "\n".join(dialog)},
                ],
                temperature=0.3,
                max_tokens=60,
            )
            summary = (raw.choices[0].message.content or "").strip()
            if summary:
                self.memory.apply_updates({"session_summary": summary})
                self.memory.save()
        except Exception:
            pass

    def opening_line(self) -> ChatResult:
        user = self.memory.data.get("user_name", "")
        hook = self.memory.pick_opening_hook()
        line = pick_opening(self.cfg, user, hook)
        emotion = "presence" if hook else "soft"
        return ChatResult(text=line, emotion=emotion)

    def tts_voice(self) -> str:
        return self.tts_config().voice

    def tts_config(self) -> TtsConfig:
        from voice_io import TtsConfig

        speaking = self.cfg.get("speaking") or {}
        emotion_cfg = self.cfg.get("emotion") or {}
        return TtsConfig(
            backend=os.getenv("TTS_BACKEND", speaking.get("tts_backend", "edge")).strip(),
            voice=os.getenv(
                "TTS_VOICE", speaking.get("tts_voice", "zh-CN-XiaoxiaoNeural")
            ).strip(),
            rate=os.getenv("TTS_RATE", speaking.get("tts_rate", "-14%")).strip(),
            volume=os.getenv("TTS_VOLUME", speaking.get("tts_volume", "-10%")).strip(),
            pitch=os.getenv("TTS_PITCH", speaking.get("tts_pitch", "-8Hz")).strip(),
            style=os.getenv("TTS_STYLE", speaking.get("tts_style", "")).strip(),
            styledegree=os.getenv(
                "TTS_STYLE_DEGREE", speaking.get("tts_styledegree", "1.2")
            ).strip(),
            piper_model=os.getenv(
                "PIPER_MODEL", speaking.get("piper_model", "")
            ).strip(),
            minimax_model=os.getenv(
                "MINIMAX_MODEL", speaking.get("minimax_model", "speech-2.8-hd")
            ).strip(),
            performative=bool(
                emotion_cfg.get(
                    "performative_tts",
                    speaking.get("performative_tts", True),
                )
            ),
        )

    def close(self) -> None:
        self.memory.save()
