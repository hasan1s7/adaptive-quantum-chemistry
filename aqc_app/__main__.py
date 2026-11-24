"""Run the development-only AQC interface without optional dependencies."""
from __future__ import annotations

import argparse
import errno
from pathlib import Path
import sys
import threading
import webbrowser

from .server import LocalHTTPServer, STATIC_FILES


def main(argv=None):
    parser = argparse.ArgumentParser(description="Open the local Adaptive Quantum Chemistry MVP; no quantum jobs or optional dependencies.")
    parser.add_argument("--port", type=int, default=8765, help="Loopback HTTP port (default: 8765)")
    parser.add_argument("--no-open", action="store_true", help="Print the URL without opening a browser")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    app_dir = Path(__file__).resolve().parents[1] / "app"
    missing = sorted({name for name, _ in STATIC_FILES.values() if not (app_dir / name).is_file()})
    if missing:
        print("Cannot start AQC: the local app bundle is incomplete: " + ", ".join(missing), file=sys.stderr)
        return 1
    try:
        server = LocalHTTPServer(app_dir=app_dir, port=args.port)
    except FileNotFoundError as error:
        print(f"Cannot start AQC: a bundled input is missing: {error.filename}. Restore the original release files.", file=sys.stderr)
        return 1
    except OSError as error:
        if error.errno in (errno.EADDRINUSE, errno.EACCES):
            print(f"Cannot start AQC on 127.0.0.1:{args.port}: {error}. Try --port with another local port.", file=sys.stderr)
        else:
            print(f"Cannot start AQC: bundled inputs could not be read: {error}. Restore the original release files.", file=sys.stderr)
        return 1
    except (ValueError, KeyError, TypeError, EOFError) as error:
        print(f"Cannot start AQC: bundled evidence verification failed: {error}. Restore the original release files.", file=sys.stderr)
        return 1
    print(f"Adaptive Quantum Chemistry local MVP: {server.url}", flush=True)
    print(f"Verified development data: {server.store.counts['molecules']} molecules, {server.store.counts['candidates']} conformers. References stay on the server until a charged query.", flush=True)
    print("Loopback only. No quantum jobs. Sessions are in memory and expire after 15 idle minutes; export traces to keep them. Press Ctrl+C to stop.", flush=True)
    if not args.no_open:
        def open_browser():
            try:
                if not webbrowser.open(server.url):
                    print("A browser could not be opened automatically; open the printed URL manually.", file=sys.stderr, flush=True)
            except Exception as error:
                print(f"Browser opening failed ({type(error).__name__}); open the printed URL manually.", file=sys.stderr, flush=True)
        threading.Thread(target=open_browser, name="aqc-open-browser", daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("\nStopping AQC and closing active policy workers.", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
