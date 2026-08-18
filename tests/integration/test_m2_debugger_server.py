from __future__ import annotations

import json
from threading import Thread
from urllib.request import urlopen

from sidestage.web.server import create_server


def test_review_server_exposes_import_trace_and_existing_static_files() -> None:
    server = create_server(host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        port = server.server_address[1]
        with urlopen(f"http://127.0.0.1:{port}/api/debug/import-trace") as response:
            trace = json.load(response)
            assert response.status == 200
            assert response.headers["Cache-Control"] == "no-store"

        assert trace["runtime_source"] == "m2_1_typed_loader"
        assert trace["status"] == "accepted"
        assert trace["outcome"]["counts"]["sellers"] == 3

        with urlopen(f"http://127.0.0.1:{port}/fixtures/sellers.json") as response:
            sellers = json.load(response)
            assert response.status == 200

        assert len(sellers["sellers"]) == 3
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
