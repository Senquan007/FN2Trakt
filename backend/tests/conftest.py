from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TMP = Path(tempfile.mkdtemp(prefix="fn2trakt-tests-"))
(TMP / "data").mkdir(parents=True, exist_ok=True)

os.environ["FN2TRAKT_DATA_DIR"] = str(TMP / "data")
os.environ["FN2TRAKT_FNTV_DB_PATH"] = str(ROOT / "DB" / "trimmedia.db")


class MockState:
    authorized = False
    token_polls = 0
    history_payloads: list[dict] = []
    device_token_bodies: list[dict] = []
    refresh_bodies: list[dict] = []
    refresh_calls = 0
    last_access_token = "access-initial"
    history_items: list[dict] = []
    webhook_payloads: list[dict] = []
    feishu_secret = "feishu-secret"


STATE = MockState()


class MockHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # silence
        pass

    def _send(self, code: int, body: dict | None = None):
        payload = json.dumps(body or {}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return {}

    def do_GET(self):
        if self.path.startswith("/users/me"):
            self._send(
                200,
                {
                    "username": "mock-user",
                    "ids": {"slug": "mock-user", "trakt": 4242},
                    "images": {"avatar": {"full": "https://example.com/a.png"}},
                },
            )
        elif self.path.startswith("/search/show"):
            self._send(
                200,
                [
                    {
                        "type": "show",
                        "score": 100,
                        "show": {
                            "title": "漫长的季节",
                            "year": 2023,
                            "ids": {"trakt": 9991, "slug": "changs", "tmdb": 225008},
                        },
                    }
                ],
            )
        elif self.path.startswith("/search/movie"):
            self._send(200, [])
        elif self.path.startswith("/sync/history"):
            items = STATE.history_items
            payload = json.dumps(items).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("X-Pagination-Page-Count", "1")
            self.send_header("X-Pagination-Item-Count", str(len(items)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        body = self._body()
        if self.path == "/oauth/device/code":
            self._send(
                200,
                {
                    "device_code": "device-abc",
                    "user_code": "ABCD1234",
                    "verification_url": "https://auth.trakt.tv/activate",
                    "expires_in": 600,
                    "interval": 1,
                },
            )
        elif self.path == "/oauth/device/token":
            STATE.token_polls += 1
            STATE.device_token_bodies.append(body)
            if not STATE.authorized:
                self._send(400, {"error": "pending"})
            else:
                STATE.last_access_token = "access-device"
                self._send(
                    200,
                    {
                        "access_token": "access-device",
                        "token_type": "bearer",
                        "expires_in": 86400,
                        "refresh_token": "refresh-device",
                        "scope": "public",
                        "created_at": 1700000000,
                    },
                )
        elif self.path == "/oauth/token":
            STATE.refresh_calls += 1
            STATE.refresh_bodies.append(body)
            STATE.last_access_token = "access-refreshed"
            self._send(
                200,
                {
                    "access_token": "access-refreshed",
                    "token_type": "bearer",
                    "expires_in": 86400,
                    "refresh_token": "refresh-refreshed",
                    "scope": "public",
                },
            )
        elif self.path == "/webhook":
            STATE.webhook_payloads.append(body)
            self._send(200, {"ok": True})
        elif self.path == "/feishu":
            # Emulates 飞书自定义机器人: HTTP 200 even when the signature is
            # wrong, with the error only visible inside the JSON body.
            STATE.webhook_payloads.append(body)
            timestamp = str(body.get("timestamp") or "")
            expected = ""
            if timestamp:
                string_to_sign = f"{timestamp}\n{STATE.feishu_secret}"
                digest = hmac.new(
                    string_to_sign.encode("utf-8"), b"", digestmod=hashlib.sha256
                ).digest()
                expected = base64.b64encode(digest).decode("utf-8")
            if body.get("msg_type") == "text" and body.get("sign") == expected:
                self._send(200, {"code": 0, "msg": "success", "data": {}})
            else:
                self._send(200, {"code": 19021, "msg": "sign match fail", "data": {}})
        elif self.path == "/sync/history":
            STATE.history_payloads.append(body)
            movies = body.get("movies") or []
            episodes = sum(
                len(season.get("episodes") or [])
                for show in (body.get("shows") or [])
                for season in (show.get("seasons") or [])
            )
            self._send(201, {"added": {"movies": len(movies), "episodes": episodes}, "not_found": {}})
        else:
            self._send(404, {"error": "not found"})


_server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
_thread = threading.Thread(target=_server.serve_forever, daemon=True)
_thread.start()
os.environ["FN2TRAKT_TRAKT_API_BASE"] = f"http://127.0.0.1:{_server.server_port}"
os.environ["FN2TRAKT_TRAKT_AUTH_BASE"] = f"http://127.0.0.1:{_server.server_port}"
os.environ["FN2TRAKT_TRAKT_TRUST_ENV"] = "false"

# Webhook endpoints in tests point back at this mock server.
STATE.base_url = f"http://127.0.0.1:{_server.server_port}"


def pytest_configure(config):
    pass
