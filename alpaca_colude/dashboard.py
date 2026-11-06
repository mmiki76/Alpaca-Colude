"""Dashboard web LOCAL pentru PaperBot (stdlib, fără dependențe). Ascultă doar pe 127.0.0.1.

GET  /            pagina
GET  /api/state   snapshot JSON
POST /api/config  {"leverage": 3, ...}        (setări validate)
POST /api/pause | /api/resume | /api/close    (pauză / reluare / închide poziția)
Cheile API NU trec niciodată pe aici (doar variabile de mediu în procesul botului).
POST-urile cer antetul `X-Requested-With: dashboard` (blochează cererile cross-site).
"""
from __future__ import annotations

import json
import math
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "dashboard.html")


def clean(o):
    """NaN/inf -> None (JSON valid)."""
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    return o


def make_handler(bot):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):          # liniște în terminal
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(clean(obj)).encode())

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("127.0.0.1", "localhost")

        def do_GET(self):
            if not self._host_ok():
                return self._json(403, {"error": "host"})
            if self.path in ("/", "/index.html"):
                with open(HTML_PATH, "rb") as f:
                    return self._send(200, f.read(), "text/html")
            if self.path == "/api/state":
                return self._json(200, bot.snapshot())
            self._json(404, {"error": "not found"})

        def do_POST(self):
            if not self._host_ok() or self.headers.get("X-Requested-With") != "dashboard":
                return self._json(403, {"error": "interzis"})
            n = int(self.headers.get("Content-Length") or 0)
            if n > 10_000:
                return self._json(413, {"error": "prea mare"})
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                if self.path == "/api/config":
                    bot.update_config(body)
                elif self.path == "/api/pause":
                    bot.pause()
                elif self.path == "/api/resume":
                    bot.resume()
                elif self.path == "/api/close":
                    bot.close_position()
                else:
                    return self._json(404, {"error": "not found"})
            except (ValueError, TypeError, json.JSONDecodeError) as e:
                return self._json(400, {"error": str(e)})
            except Exception as e:
                return self._json(500, {"error": f"{type(e).__name__}: {e}"})
            self._json(200, {"ok": True})

    return Handler


def serve(bot, port: int = 8765, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    """Pornește serverul într-un thread și îl întoarce (port=0 -> port liber, citește server.server_address)."""
    srv = ThreadingHTTPServer((host, port), make_handler(bot))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
