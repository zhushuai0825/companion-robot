#!/usr/bin/env python3
"""最小 DeepSeek 文字对话。Key 放同目录 .env，不要写进代码。"""

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).resolve().parent / ".env")

api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()

if not api_key:
    raise SystemExit("缺少 DEEPSEEK_API_KEY：请在同目录创建 .env")

client = OpenAI(api_key=api_key, base_url=base_url)


def main() -> None:
    print("DeepSeek 文字对话已启动。输入 quit 退出。\n")
    messages = [
        {"role": "system", "content": "你是树莓派上的简洁中文助手，回答简短清楚。"}
    ]
    while True:
        text = input("你: ").strip()
        if not text:
            continue
        if text.lower() in {"q", "quit", "exit"}:
            print("再见。")
            break
        messages.append({"role": "user", "content": text})
        resp = client.chat.completions.create(model=model, messages=messages)
        reply = resp.choices[0].message.content or ""
        messages.append({"role": "assistant", "content": reply})
        print(f"助手: {reply}\n")


if __name__ == "__main__":
    main()
