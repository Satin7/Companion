#!/usr/bin/env python3
"""Minimal CORS proxy for DeepSeek API — used by web-shell."""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import urllib.request
import ssl

TARGET = "https://api.deepseek.com"
PORT = 8080

class Proxy(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""

        req = urllib.request.Request(
            TARGET + self.path,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": self.headers.get("Authorization", ""),
            },
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
        print(f"[proxy] {args[0]}")

if __name__ == "__main__":
    print(f"Proxy running on http://localhost:{PORT}")
    HTTPServer(("127.0.0.1", PORT), Proxy).serve_forever()
