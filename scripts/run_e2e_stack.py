"""Start the GUI and runner APIs together for Playwright's real Docker-stage checks."""

from __future__ import annotations

import logging
import os
import signal
import threading

from fdm_strength.runner import create_runner_server
from fdm_strength.web import create_gui_server


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    gui_host = os.environ.get("FDM_GUI_HOST", "127.0.0.1")
    gui_port = int(os.environ.get("FDM_GUI_PORT", "8012"))
    runner_host = os.environ.get("FDM_RUNNER_HOST", "127.0.0.1")
    runner_port = int(os.environ.get("FDM_RUNNER_PORT", "8021"))
    data_dir = os.environ.get("FDM_GUI_DATA_DIR") or os.environ.get("FDM_RUNNER_DATA_DIR")
    gui = create_gui_server(gui_host, gui_port, data_dir=data_dir)
    runner = create_runner_server(
        runner_host,
        runner_port,
        data_dir=os.environ.get("FDM_RUNNER_DATA_DIR") or data_dir,
    )
    stopped = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stopped.set()

    signal.signal(signal.SIGTERM, request_stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, request_stop)

    servers = (runner, gui)
    threads = [
        threading.Thread(
            target=server.serve_forever, name=f"http-{server.server_port}", daemon=True
        )
        for server in servers
    ]
    for thread in threads:
        thread.start()
    print(
        f"Playwright GUI at http://{gui_host}:{gui_port}; runner at http://{runner_host}:{runner_port}",
        flush=True,
    )
    try:
        stopped.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
