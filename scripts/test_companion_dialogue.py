#!/usr/bin/env python3
"""自动对话测试：检查路遥回复长度、文艺腔、标签泄漏。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from companion_brain import CompanionBrain
from companion_persona import (
    has_formula_mismatch,
    has_invented_throat,
    is_literary_reply,
    max_chars_for,
    min_chars_for,
)

TESTS = [
    "你最喜欢我怎么叫你？",
    "你会一直陪着我吗？",
    "我不说结婚，让你陪我一辈子，你愿意吗？",
    "我爱你怎么不是最高优先级？",
    "今天上班好累",
    "你好",
    "在吗",
    "我嗓子好疼",
    "我到家了",
    "帮我查一下明天天气",
    "别说话了，我想安静",
]


def has_tag_leak(text: str) -> bool:
    return bool(re.search(r"<<emotion:", text)) or bool(re.search(r"<<action:", text))


def main() -> None:
    brain = CompanionBrain()
    issues = 0
    print("=== 路遥对话自检 ===\n")
    for q in TESTS:
        brain.messages = [brain.messages[0]]
        r = brain.chat(q)
        limit = max_chars_for(q)
        literary = is_literary_reply(r.text)
        leak = has_tag_leak(r.text)
        formula = has_formula_mismatch(q, r.text)
        too_short = len(r.text) < min_chars_for(q)
        invented_throat = has_invented_throat(q, r.text)
        ok = (
            not literary
            and not leak
            and not formula
            and not too_short
            and not invented_throat
            and len(r.text) <= limit + 40
        )
        flag = "OK" if ok else "!!"
        if not ok:
            issues += 1
        print(f"[{flag}] Q: {q}")
        print(
            f"    len={len(r.text)} limit≈{limit} min≈{min_chars_for(q)} "
            f"literary={literary} tag_leak={leak} formula={formula} "
            f"too_short={too_short} invented_throat={invented_throat}"
        )
        print(f"    A: {r.text[:180]}{'…' if len(r.text)>180 else ''}")
        print(f"    emotion={r.emotion}\n")
    brain.close()
    print(f"完成。问题轮次: {issues}/{len(TESTS)}")
    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()
