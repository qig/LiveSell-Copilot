"""Dependency-free local review server for M2 static UI and import tracing."""

from __future__ import annotations

import argparse
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Sequence
from urllib.parse import urlsplit

from sidestage.config import REPOSITORY_ROOT
from sidestage.fixtures.import_trace import trace_seller_fixture_import


IMPORT_TRACE_PATH = "/api/debug/import-trace"


class SideStageReviewHandler(SimpleHTTPRequestHandler):
    """Serve repository assets plus the bounded M2.1 diagnostic endpoint."""

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if urlsplit(self.path).path == IMPORT_TRACE_PATH:
            self._send_import_trace()
            return
        super().do_GET()

    def _send_import_trace(self) -> None:
        try:
            trace = trace_seller_fixture_import()
        except Exception:
            self._send_json(
                500,
                {
                    "schema_version": "sidestage.import_trace.error.v1",
                    "error": "IMPORT_TRACE_UNAVAILABLE",
                },
            )
            return
        self._send_json(200, trace)

    def _send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


def create_server(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    handler = partial(SideStageReviewHandler, directory=str(REPOSITORY_ROOT))
    return ThreadingHTTPServer((host, port), handler)


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Serve the SideStage M2 review UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    server = create_server(host=args.host, port=args.port)
    print(f"SideStage review server: http://{args.host}:{server.server_address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
