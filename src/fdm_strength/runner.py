"""Internal HTTP control plane for immutable Runs and the isolated stage runner."""

from __future__ import annotations

import json
import logging
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError

from fdm_strength.runner_service import RunService, RunSubmission

MAX_REQUEST_BYTES = 64 * 1024 * 1024
DEFAULT_DATA_DIR = Path("/data")
RUN_PATH = re.compile(r"^/api/runs/([0-9a-f-]{36})(?:/replay)?$")
ARTIFACT_PATH = re.compile(r"^/api/artifacts/([0-9a-f]{64})$")
LOGGER = logging.getLogger("fdm_strength.runner")


class RunnerRequestHandler(BaseHTTPRequestHandler):
    service: RunService

    def log_message(self, format: str, *args: object) -> None:
        LOGGER.info("%s - %s", self.address_string(), format % args)

    def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        self._send_bytes(
            status,
            json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _read_body(self) -> bytes | None:
        if "application/json" not in self.headers.get("Content-Type", ""):
            self._send_json(415, {"error": "Send the request as application/json"})
            return None
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "Invalid Content-Length"})
            return None
        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            self._send_json(413, {"error": "Request must be between 1 byte and 64 MB"})
            return None
        body = self.rfile.read(content_length)
        if len(body) != content_length:
            self._send_json(400, {"error": "Request body was incomplete"})
            return None
        return body

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/health":
            self._send_json(200, {"status": "ok", "application": "fdm-runner"})
            return
        artifact_match = ARTIFACT_PATH.fullmatch(path)
        if artifact_match:
            try:
                content = self.service.read_artifact(artifact_match.group(1))
            except FileNotFoundError:
                self._send_json(404, {"error": "Artifact not found"})
                return
            except (OSError, ValueError):
                LOGGER.exception("Artifact read failed")
                self._send_json(500, {"error": "Artifact could not be verified"})
                return
            self._send_bytes(200, content, "application/octet-stream")
            return
        match = RUN_PATH.fullmatch(path)
        if match and not path.endswith("/replay"):
            try:
                run = self.service.read_run(match.group(1))
            except FileNotFoundError:
                self._send_json(404, {"error": "Run not found"})
                return
            except ValueError as error:
                self._send_json(500, {"error": str(error)})
                return
            self._send_json(200, {"run": run.model_dump(mode="json")})
            return
        self._send_json(404, {"error": "Runner route not found"})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path not in {"/api/runs"} and not (
            path.startswith("/api/runs/") and path.endswith("/replay")
        ):
            self._send_json(404, {"error": "Runner route not found"})
            return
        body = self._read_body()
        if body is None:
            return
        try:
            if path == "/api/runs":
                submission = RunSubmission.model_validate_json(body)
                run, result = self.service.submit(submission)
            else:
                match = RUN_PATH.fullmatch(path)
                if match is None or not path.endswith("/replay"):
                    self._send_json(404, {"error": "Runner route not found"})
                    return
                run, result = self.service.replay(match.group(1))
        except ValidationError as error:
            self._send_json(
                400,
                {
                    "error": "Invalid Run submission",
                    "issues": [
                        {
                            "field": ".".join(str(part) for part in item["loc"]),
                            "message": item["msg"],
                        }
                        for item in error.errors(include_url=False)
                    ],
                },
            )
            return
        except (FileNotFoundError, ValueError) as error:
            self._send_json(400, {"error": str(error)})
            return
        except Exception:
            LOGGER.exception("Run request failed unexpectedly")
            self._send_json(500, {"error": "Runner could not complete the request"})
            return
        response = {"run": run.model_dump(mode="json"), "result": result}
        if run.error is not None:
            response["error"] = run.error
        self._send_json(201 if run.status == "succeeded" else 422, response)


def create_runner_server(
    host: str = "0.0.0.0",
    port: int = 8020,
    *,
    data_dir: str | Path | None = None,
    service: RunService | None = None,
) -> ThreadingHTTPServer:
    data_root = Path(data_dir or os.environ.get("FDM_RUNNER_DATA_DIR", DEFAULT_DATA_DIR)).resolve()
    run_service = service or RunService(data_root)
    handler = type(
        "ConfiguredRunnerRequestHandler", (RunnerRequestHandler,), {"service": run_service}
    )
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    logging.basicConfig(level=os.environ.get("FDM_RUNNER_LOG_LEVEL", "INFO"))
    host = os.environ.get("FDM_RUNNER_HOST", "0.0.0.0")
    port = int(os.environ.get("FDM_RUNNER_PORT", "8020"))
    server = create_runner_server(host, port)
    LOGGER.info("fdm-runner listening on %s:%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
