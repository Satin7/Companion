#!/usr/bin/env python3
"""Combined server: serves web-shell HTML + proxies API calls.
    Single port — only need to forward ONE port in VS Code."""

from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import json
import urllib.request
import urllib.error
import ssl
import os
import socket
import mimetypes

TARGET = "https://api.deepseek.com"
CORE_TARGET = "http://127.0.0.1:8000"
PORT = 8080
WEB_DIR = os.path.dirname(os.path.abspath(__file__))

class Handler(BaseHTTPRequestHandler):
    def _send_static(self, filepath: str, head_only: bool = False):
        content_type, _ = mimetypes.guess_type(filepath)
        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.end_headers()
        if not head_only:
            with open(filepath, "rb") as f:
                self.wfile.write(f.read())

    def _serve_index(self, head_only: bool = False):
        self._send_static(os.path.join(WEB_DIR, "index.html"), head_only=head_only)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/" or path == "":
            return self._serve_index()
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        filepath = os.path.join(WEB_DIR, path.lstrip("/"))
        if os.path.isfile(filepath):
            self._send_static(filepath)
        elif "text/html" in self.headers.get("Accept", "") and "." not in os.path.basename(path):
            self._serve_index()
        else:
            self.send_response(404)
            self.end_headers()

    def do_HEAD(self):
        path = self.path.split("?")[0]
        if path == "/" or path == "":
            return self._serve_index(head_only=True)
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        filepath = os.path.join(WEB_DIR, path.lstrip("/"))
        if os.path.isfile(filepath):
            self._send_static(filepath, head_only=True)
        elif "text/html" in self.headers.get("Accept", "") and "." not in os.path.basename(path):
            self._serve_index(head_only=True)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""

        path = self.path
        target_base = TARGET
        target_path = path
        if path.startswith("/core/"):
            target_base = CORE_TARGET
            target_path = "/" + path[len("/core/") :]

        req = urllib.request.Request(
            target_base + target_path,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": self.headers.get("Authorization", ""),
                "X-Deepseek-Api-Key": self.headers.get("X-Deepseek-Api-Key", ""),
            },
            method="POST",
        )
        ctx = ssl.create_default_context()
        timeout_s = 120 if target_base == CORE_TARGET else 90
        try:
            if target_base == CORE_TARGET:
                with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                    data = resp.read()
                    self.send_response(resp.status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(data)
            else:
                with urllib.request.urlopen(req, context=ctx, timeout=timeout_s) as resp:
                    data = resp.read()
                    self.send_response(resp.status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(data)
        except urllib.error.HTTPError as e:
            err = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(err)
        except (urllib.error.URLError, TimeoutError, socket.timeout) as e:
            self.send_response(504)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"detail": f"proxy timeout: {e}"}).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def log_message(self, fmt, *args):
        print(f"[Companion] {args[0]}")

if __name__ == "__main__":
    print(f"\n  Companion Web Shell → http://localhost:{PORT}\n")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
