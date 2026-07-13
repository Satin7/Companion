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

TARGET = "https://api.deepseek.com"
CORE_TARGET = "http://127.0.0.1:8000"
PORT = 8080
WEB_DIR = os.path.dirname(os.path.abspath(__file__))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/" or path == "":
            path = "/index.html"
        filepath = os.path.join(WEB_DIR, path.lstrip("/"))
        if os.path.isfile(filepath):
            self.send_response(200)
            ct = "text/html" if path.endswith(".html") else "text/css" if path.endswith(".css") else "application/javascript"
            self.send_header("Content-Type", ct)
            self.end_headers()
            with open(filepath, "rb") as f:
                self.wfile.write(f.read())
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
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def log_message(self, fmt, *args):
        print(f"[Companion] {args[0]}")

if __name__ == "__main__":
    print(f"\n  Companion Web Shell → http://localhost:{PORT}\n")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
