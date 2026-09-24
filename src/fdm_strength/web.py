"""Local HTTP server for the browser interface and host-backed studies."""

from __future__ import annotations

import json
import logging
import math
import mimetypes
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from fdm_strength.gui_analysis import analyze_tensile_rows

MAX_REQUEST_BYTES = 64 * 1024 * 1024
MAX_ROW_COUNT = 100_000
MAX_COLUMN_COUNT = 200
DEFAULT_STATIC_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"
DEFAULT_DATA_DIR = Path.cwd() / "outputs" / "gui"
STUDY_PATH = re.compile(r"^/api/studies/([0-9a-f-]{36})$")
LOGGER = logging.getLogger("fdm_strength.web")


def _study_id(path: str) -> str | None:
    match = STUDY_PATH.fullmatch(path)
    if match is None:
        return None
    try:
        return str(uuid.UUID(match.group(1)))
    except ValueError:
        return None


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def _parse_finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON numbers must be finite")
    return number


def _validated_workspace(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("format") != "styrkeanalyse-fdm-study" or payload.get("version") != 1:
        raise ValueError("Unsupported study workspace format")
    if not isinstance(payload.get("study_name"), str) or not payload["study_name"].strip():
        raise ValueError("study_name must be a non-empty string")
    if len(payload["study_name"]) > 200:
        raise ValueError("study_name must be at most 200 characters")
    if not isinstance(payload.get("source_file_name"), str):
        raise ValueError("source_file_name must be a string")
    if len(payload["source_file_name"]) > 255:
        raise ValueError("source_file_name must be at most 255 characters")
    columns = payload.get("columns")
    if (
        not isinstance(columns, list)
        or len(columns) > MAX_COLUMN_COUNT
        or any(not isinstance(column, str) for column in columns)
    ):
        raise ValueError(f"columns must be a list of at most {MAX_COLUMN_COUNT} strings")
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) > MAX_ROW_COUNT:
        raise ValueError(f"rows must be a list of at most {MAX_ROW_COUNT:,} measurements")
    if any(
        not isinstance(row, dict)
        or any(not isinstance(key, str) for key in row)
        or any(isinstance(value, (dict, list)) for value in row.values())
        for row in rows
    ):
        raise ValueError("rows must contain scalar column values")
    settings = payload.get("settings", {})
    if not isinstance(settings, dict) or any(not isinstance(key, str) for key in settings):
        raise ValueError("settings must be an object")
    if any(isinstance(value, (dict, list)) for value in settings.values()):
        raise ValueError("settings must contain scalar values")
    result = payload.get("result")
    if result is not None and not isinstance(result, dict):
        raise ValueError("result must be an object or null")
    return {
        "format": "styrkeanalyse-fdm-study",
        "version": 1,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "analysis_time": payload.get("analysis_time", "")
        if isinstance(payload.get("analysis_time", ""), str)
        else "",
        "study_name": payload["study_name"].strip(),
        "source_file_name": payload["source_file_name"],
        "columns": columns,
        "rows": rows,
        "settings": settings,
        "result": result,
    }


class GuiRequestHandler(BaseHTTPRequestHandler):
    """Serve the compiled interface and its local analysis/storage API."""

    static_root = DEFAULT_STATIC_DIR
    data_root = DEFAULT_DATA_DIR

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
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def _read_json_object(self) -> dict[str, Any] | None:
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
        try:
            payload = json.loads(
                self.rfile.read(content_length),
                parse_constant=_reject_json_constant,
                parse_float=_parse_finite_float,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            self._send_json(400, {"error": "Request body must be valid JSON"})
            return None
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "Request body must be a JSON object"})
            return None
        return payload

    def _study_file(self, study_id: str) -> Path:
        return self.data_root / "studies" / f"{study_id}.json"

    def _save_study(self, study_id: str, workspace: dict[str, Any]) -> None:
        study_dir = self.data_root / "studies"
        study_dir.mkdir(parents=True, exist_ok=True)
        target = self._study_file(study_id)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=study_dir, prefix=f".{study_id}.", delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(
                    {"id": study_id, **workspace},
                    temporary,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                temporary.write("\n")
            os.replace(temporary_path, target)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/health":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "application": "styrkeanalyse-fdm",
                    "available_analyses": ["tensile-baseline"],
                    "study_storage": "host-backed",
                },
            )
            return
        if path == "/api/studies":
            studies = []
            for study_path in (self.data_root / "studies").glob("*.json"):
                try:
                    study = json.loads(study_path.read_text(encoding="utf-8"))
                    studies.append(
                        {
                            "id": study["id"],
                            "study_name": study["study_name"],
                            "source_file_name": study["source_file_name"],
                            "saved_at": study["saved_at"],
                            "analysis_time": study.get("analysis_time", ""),
                        }
                    )
                except (OSError, KeyError, json.JSONDecodeError):
                    continue
            studies.sort(key=lambda item: item["saved_at"], reverse=True)
            self._send_json(200, {"studies": studies})
            return
        if path.startswith("/api/studies/"):
            study_id = _study_id(path)
            study_path = self._study_file(study_id) if study_id else None
            if study_path is None:
                self._send_json(400, {"error": "Invalid study ID"})
                return
            try:
                study = json.loads(study_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                self._send_json(404, {"error": "Study not found"})
            except (OSError, json.JSONDecodeError):
                self._send_json(500, {"error": "Could not read the saved study"})
            else:
                self._send_json(200, study)
            return
        if path.startswith("/api/"):
            self._send_json(404, {"error": "API route not found"})
            return

        relative = unquote(path).lstrip("/") or "index.html"
        target = (self.static_root / relative).resolve()
        if target != self.static_root and self.static_root not in target.parents:
            self._send_json(403, {"error": "Invalid asset path"})
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            if Path(relative).suffix:
                self._send_json(404, {"error": "Asset not found"})
                return
            target = self.static_root / "index.html"
        try:
            body = target.read_bytes()
        except OSError:
            self._send_json(503, {"error": "GUI assets are not built yet"})
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript"}:
            content_type += "; charset=utf-8"
        self._send_bytes(200, body, content_type)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/studies":
            payload = self._read_json_object()
            if payload is None:
                return
            try:
                workspace = _validated_workspace(payload)
            except ValueError as error:
                self._send_json(400, {"error": str(error)})
                return
            study_id = str(uuid.uuid4())
            try:
                self._save_study(study_id, workspace)
            except OSError:
                LOGGER.exception("Failed to save study %s", study_id)
                self._send_json(500, {"error": "Desktop study storage is unavailable"})
                return
            LOGGER.info("Saved study %s with %s measurement rows", study_id, len(workspace["rows"]))
            self._send_json(201, {"id": study_id, "saved_at": workspace["saved_at"]})
            return
        if path != "/api/analysis/tensile":
            self._send_json(404, {"error": "API route not found"})
            return
        payload = self._read_json_object()
        if payload is None:
            return
        rows = payload.get("rows")
        if isinstance(rows, list) and len(rows) > MAX_ROW_COUNT:
            self._send_json(
                413, {"error": f"At most {MAX_ROW_COUNT:,} rows can be analysed at once"}
            )
            return
        try:
            result = analyze_tensile_rows(
                rows=rows,
                force_column=payload.get("force_column"),
                displacement_column=payload.get("displacement_column"),
                width_mm=payload.get("width_mm"),
                thickness_mm=payload.get("thickness_mm"),
                gauge_length_mm=payload.get("gauge_length_mm"),
                force_unit=payload.get("force_unit", "N"),
                displacement_unit=payload.get("displacement_unit", "mm"),
                decimal_separator=payload.get("decimal_separator", "."),
                tension_direction=payload.get("tension_direction", "positive"),
            )
        except (TypeError, ValueError) as error:
            self._send_json(400, {"error": str(error)})
            return
        summary = {key: value for key, value in result.items() if key != "points"}
        self._send_json(200, {"summary": summary, "points": result["points"]})

    def do_PUT(self) -> None:
        path = urlsplit(self.path).path
        study_id = _study_id(path)
        if study_id is None:
            self._send_json(404, {"error": "Study route not found"})
            return
        if not self._study_file(study_id).is_file():
            self._send_json(404, {"error": "Study not found"})
            return
        payload = self._read_json_object()
        if payload is None:
            return
        try:
            workspace = _validated_workspace(payload)
        except ValueError as error:
            self._send_json(400, {"error": str(error)})
            return
        try:
            self._save_study(study_id, workspace)
        except OSError:
            LOGGER.exception("Failed to update study %s", study_id)
            self._send_json(500, {"error": "Desktop study storage is unavailable"})
            return
        LOGGER.info("Updated study %s with %s measurement rows", study_id, len(workspace["rows"]))
        self._send_json(200, {"id": study_id, "saved_at": workspace["saved_at"]})


def create_gui_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    static_dir: str | Path | None = None,
    data_dir: str | Path | None = None,
) -> ThreadingHTTPServer:
    """Create a server; bind to loopback by default."""
    static_root = Path(
        static_dir or os.environ.get("FDM_GUI_STATIC_DIR", DEFAULT_STATIC_DIR)
    ).resolve()
    data_root = Path(data_dir or os.environ.get("FDM_GUI_DATA_DIR", DEFAULT_DATA_DIR)).resolve()
    handler = type(
        "ConfiguredGuiRequestHandler",
        (GuiRequestHandler,),
        {"static_root": static_root, "data_root": data_root},
    )
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    logging.basicConfig(level=os.environ.get("FDM_GUI_LOG_LEVEL", "INFO"))
    host = os.environ.get("FDM_GUI_HOST", "127.0.0.1")
    port = int(os.environ.get("FDM_GUI_PORT", "8000"))
    server = create_gui_server(host, port)
    print(f"StyrkeAnalyse FDM GUI available at http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
