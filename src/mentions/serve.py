"""Build the site and serve it locally.

    uv run mentions-serve

Then open http://127.0.0.1:8765 . The same site/ directory is what GitHub
Pages publishes. Rebuilds once at startup; restart to pick up a newer scan.
"""

from __future__ import annotations

import os
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

from mentions.build_site import SITE, build

PORT = int(os.environ.get("PORT", "8765"))


def main() -> None:
    build()
    os.chdir(SITE)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), SimpleHTTPRequestHandler)
    print(f"serving {SITE} at http://127.0.0.1:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
