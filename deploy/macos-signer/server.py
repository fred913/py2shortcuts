#!/usr/bin/env python3
"""Small authenticated HTTP wrapper around macOS `shortcuts sign`."""

from __future__ import annotations

import argparse
import hmac
import plistlib
import subprocess
import tempfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_REQUEST_BYTES = 1024 * 1024


class SigningServer(ThreadingHTTPServer):
    api_token: str
    shortcuts_path: str


class Handler(BaseHTTPRequestHandler):
    server: SigningServer

    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        result = subprocess.run(
            [self.server.shortcuts_path, "help", "sign"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "shortcuts CLI unavailable")
            return
        body = b"ok\n"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path != "/v1/sign":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        expected = f"Bearer {self.server.api_token}"
        supplied = self.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied, expected):
            self.send_error(HTTPStatus.UNAUTHORIZED)
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "invalid Content-Length")
            return
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        workflow = self.rfile.read(length)
        try:
            parsed = plistlib.loads(workflow)
        except plistlib.InvalidFileException:
            self.send_error(HTTPStatus.BAD_REQUEST, "invalid plist")
            return
        if not isinstance(parsed, dict) or not isinstance(parsed.get("WFWorkflowActions"), list):
            self.send_error(HTTPStatus.BAD_REQUEST, "not a Shortcuts workflow")
            return

        try:
            with tempfile.TemporaryDirectory(prefix="py2shortcuts-sign-") as directory:
                input_path = Path(directory, "input.wflow")
                output_path = Path(directory, "output.shortcut")
                input_path.write_bytes(workflow)
                result = subprocess.run(
                    [
                        self.server.shortcuts_path,
                        "sign",
                        "--mode",
                        "anyone",
                        "--input",
                        str(input_path),
                        "--output",
                        str(output_path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
                if result.returncode != 0:
                    self.log_error("shortcuts sign failed: %s", result.stderr.strip())
                    self.send_error(HTTPStatus.BAD_GATEWAY, "shortcuts sign failed")
                    return
                signed = output_path.read_bytes()
        except (OSError, subprocess.TimeoutExpired) as error:
            self.log_error("signing failed: %s", error)
            self.send_error(HTTPStatus.BAD_GATEWAY, "signing failed")
            return
        if not signed.startswith(b"AEA1"):
            self.send_error(HTTPStatus.BAD_GATEWAY, "invalid signed output")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(signed)))
        self.end_headers()
        self.wfile.write(signed)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--shortcuts", default="/usr/bin/shortcuts")
    parser.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args()
    token = args.token_file.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("Signing token file is empty")
    server = SigningServer((args.host, args.port), Handler)
    server.api_token = token
    server.shortcuts_path = args.shortcuts
    server.serve_forever()


if __name__ == "__main__":
    main()
