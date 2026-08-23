#!/usr/bin/env python3
"""导出微调数据集：人设圣经 + 范例库 → OpenAI JSONL 格式。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "data" / "dialogue_examples.jsonl"
PERSONA = ROOT / "config" / "persona_luoyao.yaml"
OUT = ROOT / "data" / "finetune_luoyao.jsonl"


def build_system_stub() -> str:
  return (
      "你是路遥。从另一边来到用户日常里的情感陪伴。"
      "男声低柔稳，短句，共鸣先于分析，不当客服或心理咨询师。"
      "每轮 1-3 句，可留白……"
  )


def main() -> None:
    lines: list[str] = []
    system = build_system_stub()
    if EXAMPLES.exists():
        for raw in EXAMPLES.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            obj = json.loads(raw)
            user = obj.get("user", "").strip()
            assistant = obj.get("assistant", "").strip()
            emotion = obj.get("emotion", "neutral")
            if not user or not assistant:
                continue
            record = {
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                    {
                        "role": "assistant",
                        "content": f"{assistant}\n<<emotion:{emotion}>>",
                    },
                ]
            }
            lines.append(json.dumps(record, ensure_ascii=False))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    print(f"已导出 {len(lines)} 条 → {OUT}")
    print("可用于 LLaMA-Factory / ms-swift / OpenAI fine-tune 格式。")


if __name__ == "__main__":
    main()
