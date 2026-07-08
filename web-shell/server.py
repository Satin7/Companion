#!/usr/bin/env python3
"""Combined server: serves web-shell HTML + proxies DeepSeek API calls.
   Single port — only need to forward ONE port in VS Code."""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import urllib.request
import ssl
import os

TARGET = "https://api.deepseek.com"
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
        req = urllib.request.Request(
            TARGET + self.path,
            data=body,
            headers={"Content-Type": "application/json", "Authorization": self.headers.get("Authorization", "")},
            method="POST",
        )
        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
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
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
