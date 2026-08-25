#!/usr/bin/env python3
"""Mac 桌面代理：让树莓派路遥远程打开备忘录、通知、剪贴板等。

在 Mac 上运行：
  export DESKTOP_AGENT_TOKEN=随便设一个口令
  python3 scripts/desktop_agent.py

树莓派 src/.env：
  COMPANION_ACTIONS=1
  DESKTOP_AGENT_URL=http://192.168.2.10:8765
  DESKTOP_AGENT_TOKEN=同上口令
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from companion_actions import run_action

HOST = os.getenv("DESKTOP_AGENT_HOST", "0.0.0.0")
PORT = int(os.getenv("DESKTOP_AGENT_PORT", "8765"))
TOKEN = os.getenv("DESKTOP_AGENT_TOKEN", "").strip()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print(f"[agent] {self.address_string()} {fmt % args}")

    def _auth_ok(self) -> bool:
        if not TOKEN:
            return True
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {TOKEN}"

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true,"service":"companion-desktop-agent"}')
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path != "/action":
            self.send_response(404)
            self.end_headers()
            return
        if not self._auth_ok():
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"ok":false,"error":"unauthorized"}')
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
            action = str(data.get("action", "")).strip()
            arg = str(data.get("arg", "")).strip()
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"ok":false,"error":"bad json"}')
            return
        os.environ["COMPANION_ACTIONS"] = "1"
        ok = run_action(action, arg)
        body = json.dumps({"ok": ok, "action": action}).encode("utf-8")
        self.send_response(200 if ok else 500)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    if os.uname().sysname != "Darwin":
        raise SystemExit("desktop_agent 仅支持 macOS")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Desktop agent http://{HOST}:{PORT}  (token={'set' if TOKEN else 'none'})")
    print("POST /action  {\"action\":\"memo\",\"arg\":\"记得喝水\"}")
    server.serve_forever()


if __name__ == "__main__":
    main()
