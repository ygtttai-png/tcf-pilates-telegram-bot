import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path


sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot import run_check, send_error_message  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        cron_secret = os.getenv("CRON_SECRET")
        if cron_secret and self.headers.get("authorization") != f"Bearer {cron_secret}":
            self._send_json({"ok": False, "error": "Unauthorized"}, status=401)
            return

        try:
            result = run_check()
            self._send_json(result)
        except Exception as exc:
            send_error_message(exc)
            self._send_json(
                {
                    "ok": False,
                    "error": type(exc).__name__,
                    "message": str(exc),
                },
                status=500,
            )

    def do_POST(self) -> None:
        self.do_GET()

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
