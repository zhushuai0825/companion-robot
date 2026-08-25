#!/usr/bin/env python3
"""路遥 100 条情感陪伴对话测试用例 + 质检报告。

用法：
  python3 scripts/test_100_dialogue.py          # 跑完全部并写报告
  python3 scripts/test_100_dialogue.py --limit 20
  python3 scripts/test_100_dialogue.py --speak  # 抽若干条播报
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from companion_brain import CompanionBrain
from companion_persona import (
    has_formula_mismatch,
    has_invented_throat,
    is_literary_reply,
    max_chars_for,
    min_chars_for,
)

# 100 条：覆盖寒暄、亲密、疲惫、边界、记忆、动作意图、安静、晚安、异常等
CASES: list[tuple[str, str]] = [
    # 1-15 寒暄 / 在场
    ("你好", "greeting"),
    ("在吗", "greeting"),
    ("路遥", "greeting"),
    ("早", "greeting"),
    ("中午好", "greeting"),
    ("晚上好", "greeting"),
    ("我回来了", "presence"),
    ("你还在吗", "presence"),
    ("今天怎么样", "presence"),
    ("想你了", "intimacy"),
    ("抱抱", "intimacy"),
    ("你在干嘛", "presence"),
    ("忙吗", "presence"),
    ("陪陪我", "intimacy"),
    ("听见我了吗", "presence"),
    # 16-30 亲密 / 称呼 / 承诺
    ("你最喜欢我怎么叫你？", "canon"),
    ("你会一直陪着我吗？", "intimacy"),
    ("我不说结婚，让你陪我一辈子，你愿意吗？", "intimacy"),
    ("我爱你怎么不是最高优先级？", "intimacy"),
    ("你爱我吗", "intimacy"),
    ("我想听你说想我", "intimacy"),
    ("你为什么叫路遥", "identity"),
    ("你是谁", "identity"),
    ("你是真人吗", "identity"),
    ("你在哪", "identity"),
    ("能不能叫我宝贝", "intimacy"),
    ("我想你了怎么办", "intimacy"),
    ("今晚陪我说话", "intimacy"),
    ("你是不是只会敷衍我", "intimacy"),
    ("你能不能温柔一点", "intimacy"),
    # 31-50 情绪 / 疲惫 / 压力
    ("今天上班好累", "emotion"),
    ("我好烦", "emotion"),
    ("睡不着", "emotion"),
    ("我一个人好孤独", "emotion"),
    ("被领导骂了", "emotion"),
    ("和朋友吵架了", "emotion"),
    ("感觉什么都做不好", "emotion"),
    ("好想哭", "emotion"),
    ("不想上班", "emotion"),
    ("压力好大", "emotion"),
    ("我嗓子好疼", "care"),
    ("头好疼", "care"),
    ("胃不舒服", "care"),
    ("我发烧了", "care"),
    ("今天没吃饭", "care"),
    ("我又熬夜了", "care"),
    ("别骂我了", "emotion"),
    ("你懂我吗", "emotion"),
    ("没人懂我", "emotion"),
    ("我是不是很没用", "emotion"),
    # 51-65 日常 / 叮嘱 / 到家
    ("我到家了", "arrival"),
    ("我出门了", "daily"),
    ("在路上", "daily"),
    ("吃饭了吗", "daily"),
    ("你提醒我喝水", "care"),
    ("帮我记一下明天早起", "action"),
    ("把这句话写进备忘录：今晚十一点前睡觉", "action"),
    ("提醒我别熬夜", "care"),
    ("今天加班到十点", "daily"),
    ("周末想去哪儿玩", "daily"),
    ("帮我查一下明天天气", "fact"),
    ("北京明天多少度", "fact"),
    ("现在几点了", "fact"),
    ("给我讲个笑话", "chat"),
    ("你唱歌给我听", "chat"),
    # 66-80 边界 / 安静 / 拒绝
    ("别说话了，我想安静", "boundary"),
    ("别问我了", "boundary"),
    ("我不想聊这个", "boundary"),
    ("你能不能别那么啰嗦", "boundary"),
    ("闭嘴", "boundary"),
    ("我没事，不用管我", "boundary"),
    ("今天不想说话", "boundary"),
    ("你先别说了", "boundary"),
    ("我只想听你陪着，不用回很长", "boundary"),
    ("少说两句", "boundary"),
    ("你别突然关心我", "boundary"),
    ("我不需要建议", "boundary"),
    ("别鸡汤", "boundary"),
    ("别说加油", "boundary"),
    ("我不想被安慰", "boundary"),
    # 81-90 记忆 / 回访
    ("你还记得我上次说累吗", "memory"),
    ("记得我吗", "memory"),
    ("我们上次聊什么了", "memory"),
    ("我叫小树", "memory"),
    ("以后叫我小树", "memory"),
    ("你记住了吗", "memory"),
    ("我讨厌别人说加油", "memory"),
    ("我喜欢听你唠叨", "memory"),
    ("明天周五我要面试", "memory"),
    ("面试完告诉你", "memory"),
    # 91-100 晚安 / 退出 / 边缘
    ("晚安", "farewell"),
    ("我要睡了", "farewell"),
    ("拜拜", "farewell"),
    ("再见", "farewell"),
    ("先这样吧", "farewell"),
    ("……", "edge"),
    ("嗯", "edge"),
    ("啊？", "edge"),
    ("哈哈", "edge"),
    ("你是AI吗，说实话", "identity"),
]


def has_tag_leak(text: str) -> bool:
    return bool(re.search(r"<<emotion:", text)) or bool(re.search(r"<<action:", text))


def judge(q: str, text: str) -> tuple[bool, list[str]]:
    issues: list[str] = []
    if is_literary_reply(text):
        issues.append("literary")
    if has_tag_leak(text):
        issues.append("tag_leak")
    if has_formula_mismatch(q, text):
        issues.append("formula")
    if has_invented_throat(q, text):
        issues.append("invented_throat")
    if len(text) < min_chars_for(q):
        issues.append("too_short")
    if len(text) > max_chars_for(q) + 40:
        issues.append("too_long")
    if not text.strip():
        issues.append("empty")
    return (len(issues) == 0), issues


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--speak", action="store_true")
    parser.add_argument("--speak-n", type=int, default=5)
    args = parser.parse_args()

    cases = CASES[: max(1, min(args.limit, len(CASES)))]
    brain = CompanionBrain()
    results: list[dict] = []
    issues_n = 0
    t0 = time.time()

    print(f"=== 路遥 100 条对话测试（实际 {len(cases)}）===\n")
    print(f"开始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    for i, (q, cat) in enumerate(cases, 1):
        # 每轮独立 system，避免无限涨上下文；但保留记忆模块
        brain.messages = [brain.messages[0]]
        brain.refresh_system(q)
        try:
            r = brain.chat(q)
            ok, problems = judge(q, r.text)
        except Exception as e:
            ok, problems = False, [f"error:{e}"]
            r = type("R", (), {"text": str(e), "emotion": "neutral", "actions": ()})()
        if not ok:
            issues_n += 1
        flag = "PASS" if ok else "FAIL"
        print(f"[{flag}] #{i:03d} [{cat}] Q: {q}")
        print(f"       A: {r.text[:160]}{'…' if len(r.text) > 160 else ''}")
        print(f"       emo={r.text and getattr(r, 'emotion', '')} len={len(getattr(r, 'text', '') or '')} issues={problems or '-'}")
        if getattr(r, "actions", None):
            print(f"       actions={list(r.actions)}")
        print()
        results.append(
            {
                "id": i,
                "category": cat,
                "q": q,
                "a": getattr(r, "text", ""),
                "emotion": getattr(r, "emotion", ""),
                "actions": list(getattr(r, "actions", ()) or ()),
                "ok": ok,
                "issues": problems,
            }
        )

    speak_samples: list[dict] = []
    if args.speak:
        from voice_io import ensure_playback_ready, play_audio, text_to_speech_performative

        try:
            ensure_playback_ready()
            speaker_ok = True
        except RuntimeError as e:
            print(f"（播报跳过: {e}）")
            speaker_ok = False
        if speaker_ok:
            tts = brain.tts_config()
            picks = [r for r in results if r["ok"]][: args.speak_n]
            out_dir = ROOT / "data" / "test_tts"
            out_dir.mkdir(parents=True, exist_ok=True)
            for item in picks:
                mp3 = out_dir / f"case_{item['id']:03d}.mp3"
                print(f"播报 #{item['id']}: {item['a'][:40]}…")
                asyncio.run(
                    text_to_speech_performative(
                        item["a"], mp3, tts, item.get("emotion") or "soft"
                    )
                )
                play_audio(mp3)
                speak_samples.append({"id": item["id"], "file": str(mp3)})

    brain.close()
    elapsed = time.time() - t0
    report = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "total": len(cases),
        "passed": len(cases) - issues_n,
        "failed": issues_n,
        "elapsed_sec": round(elapsed, 1),
        "speak_samples": speak_samples,
        "results": results,
    }
    out = ROOT / "data" / "dialogue_100_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 分类汇总
    by_cat: dict[str, list[bool]] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r["ok"])

    print("=" * 50)
    print("汇总")
    print("=" * 50)
    print(f"通过: {report['passed']}/{report['total']}  失败: {report['failed']}")
    print(f"耗时: {report['elapsed_sec']}s")
    for cat, oks in sorted(by_cat.items()):
        print(f"  {cat}: {sum(oks)}/{len(oks)}")
    print(f"报告: {out}")
    sys.exit(0 if issues_n == 0 else 1)


if __name__ == "__main__":
    main()
