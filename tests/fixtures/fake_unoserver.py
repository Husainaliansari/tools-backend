"""Stand-in for the ``unoserver`` server process used in tests.

Mimics the startup contract the office pool relies on: parses ``--port``,
binds a TCP listener on it (the pool's health check is a connect), then
serves until killed. Environment-variable failure modes:

* ``FAKE_UNOSERVER_EXIT=1`` — exit non-zero immediately, simulating a
  launcher that resolves but cannot actually start (e.g. a Python without
  ``uno`` bindings).
* ``FAKE_UNOSERVER_ONESHOT=1`` — serve exactly one connection (the pool's
  health check) and then exit, simulating LibreOffice dying on the first
  conversion (seen with builds that cannot run under UNO control).
"""

from __future__ import annotations

import os
import socket
import sys


def main(argv: list[str]) -> int:
    if os.environ.get("FAKE_UNOSERVER_EXIT"):
        sys.stderr.write("simulated startup failure\n")
        return 3

    port = int(argv[argv.index("--port") + 1])
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", port))
        server.listen(5)
        while True:
            connection, _ = server.accept()
            connection.close()
            if os.environ.get("FAKE_UNOSERVER_ONESHOT"):
                sys.stderr.write("simulated LibreOffice death\n")
                return 81


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
