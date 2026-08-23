#!/usr/bin/env python3
"""情感陪伴文字模式（调试人设 / 记忆 / 范例检索）。"""

from companion_brain import CompanionBrain


def main() -> None:
    brain = CompanionBrain()
    name = brain.cfg.get("name", "小伴")
    print(f"「{name}」文字陪伴已启动（路遥全局人设 + 长期记忆）。")
    print("输入 quit 退出。\n")

    opening = brain.opening_line()
    print(f"{name}: {opening.text}  [{opening.emotion}]\n")

    try:
        while True:
            text = input("你: ").strip()
            if not text:
                continue
            if text.lower() in {"q", "quit", "exit"}:
                break
            result = brain.chat(text)
            print(f"{name}: {result.text}  [{result.emotion}]\n")
    finally:
        brain.close()
        print("再见。")


if __name__ == "__main__":
    main()
