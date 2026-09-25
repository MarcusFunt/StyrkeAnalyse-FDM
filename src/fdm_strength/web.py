"""Local HTTP server for the browser interface and host-backed studies."""

from __future__ import annotations

import json
import logging
import math
import mimetypes
import os
import re
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

from fdm_strength.study_models import StudyWorkspaceV3, migrate_workspace_v2_to_v3

MAX_REQUEST_BYTES = 64 * 1024 * 1024
MAX_ROW_COUNT = 100_000
MAX_COLUMN_COUNT = 200
DEFAULT_STATIC_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"
DEFAULT_DATA_DIR = Path.cwd() / "outputs" / "gui"
STUDY_PATH = re.compile(r"^/api/studies/([0-9a-f-]{36})$")
STUDY_ACTION_PATH = re.compile(r"^/api/studies/([0-9a-f-]{36})/(restore|permanent)$")
RUN_PATH = re.compile(r"^/api/runs/([0-9a-f-]{36})$")
JOB_PATH = re.compile(r"^/api/jobs/([0-9a-f-]{36})$")
RUN_REPLAY_PATH = re.compile(r"^/api/runs/([0-9a-f-]{36})/replay$")
ARTIFACT_PATH = re.compile(r"^/api/artifacts/([0-9a-f]{64})$")
DEFAULT_RETENTION_DAYS = 30
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 3650
STUDY_LOCK = threading.RLock()
LOGGER = logging.getLogger("fdm_strength.web")


def _study_id(path: str) -> str | None:
    match = STUDY_PATH.fullmatch(path)
    if match is None:
        return None
    try:
        return str(uuid.UUID(match.group(1)))
    except ValueError:
        return None


def _study_action(path: str) -> tuple[str, str] | None:
    match = STUDY_ACTION_PATH.fullmatch(path)
    if match is None:
        return None
    try:
        return str(uuid.UUID(match.group(1))), match.group(2)
    except ValueError:
        return None


def _revision(study: dict[str, Any]) -> int:
    revision = study.get("revision", 1)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("Saved study has an invalid revision")
    return revision


def _retention_path(data_root: Path) -> Path:
    return data_root / "retention-policy.json"


def _retention_days(data_root: Path) -> int:
    try:
        payload = json.loads(_retention_path(data_root).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return DEFAULT_RETENTION_DAYS
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Could not read the study retention policy") from error
    days = payload.get("retention_days") if isinstance(payload, dict) else None
    if (
        isinstance(days, bool)
        or not isinstance(days, int)
        or not MIN_RETENTION_DAYS <= days <= MAX_RETENTION_DAYS
    ):
        raise ValueError("Saved study retention policy is invalid")
    return days


def _write_json_atomically(target: Path, payload: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent, prefix=f".{target.stem}.", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(payload, temporary, ensure_ascii=False, allow_nan=False)
            temporary.write("\n")
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _purge_expired_studies(data_root: Path, now: datetime | None = None) -> int:
    days = _retention_days(data_root)
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    studies_dir = data_root / "studies"
    purged = 0
    if not studies_dir.exists():
        return purged
    for path in studies_dir.glob("*.json"):
        try:
            study = json.loads(path.read_text(encoding="utf-8"))
            deleted_at = datetime.fromisoformat(study["deleted_at"].replace("Z", "+00:00"))
            if deleted_at.tzinfo is None:
                continue
            if deleted_at <= cutoff:
                path.unlink()
                purged += 1
        except (OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError, ValueError):
            continue
    return purged


def _etag(revision: int) -> str:
    return f'"{revision}"'


def _expected_revision(header: str) -> int | None:
    match = re.fullmatch(r'\s*"?(\d+)"?\s*', header)
    return int(match.group(1)) if match else None


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def _parse_finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON numbers must be finite")
    return number


def _is_json_scalar(value: Any) -> bool:
    return (
        value is None
        or isinstance(value, (str, bool, int))
        or (isinstance(value, float) and math.isfinite(value))
    )


def _validated_analysis_result(result: Any) -> bool:
    if result is None:
        return True
    if not isinstance(result, dict) or set(result) != {"summary", "points"}:
        return False
    summary = result["summary"]
    points = result["points"]
    summary_fields = {
        "sample_count",
        "cross_section_area_mm2",
        "gauge_length_mm",
        "peak_force_n",
        "peak_force_row",
        "peak_stress_mpa",
        "peak_stress_row",
    }
    point_fields = {
        "row_number",
        "force_n",
        "displacement_mm",
        "extension_mm",
        "strain",
        "stress_mpa",
    }
    if (
        not isinstance(summary, dict)
        or set(summary) != summary_fields
        or not isinstance(points, list)
    ):
        return False
    count = summary["sample_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 1 or count != len(points):
        return False
    for key in ("cross_section_area_mm2", "gauge_length_mm", "peak_force_n", "peak_stress_mpa"):
        value = summary[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            return False
    if (
        summary["cross_section_area_mm2"] <= 0
        or summary["gauge_length_mm"] <= 0
        or summary["peak_force_n"] < 0
        or summary["peak_stress_mpa"] < 0
    ):
        return False
    for key in ("peak_force_row", "peak_stress_row"):
        row_number = summary[key]
        if (
            isinstance(row_number, bool)
            or not isinstance(row_number, int)
            or not 1 <= row_number <= count
        ):
            return False
    for expected_row, point in enumerate(points, start=1):
        if (
            not isinstance(point, dict)
            or set(point) != point_fields
            or point["row_number"] != expected_row
        ):
            return False
        for key in point_fields - {"row_number"}:
            value = point[key]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                return False
    return True


def _validated_workspace(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("format") != "styrkeanalyse-fdm-study":
        raise ValueError("Unsupported study workspace format")
    version = payload.get("version")
    if version == 2 or version == 3:
        from pydantic import ValidationError

        try:
            migrated_payload = migrate_workspace_v2_to_v3(payload) if version == 2 else payload
            validated = StudyWorkspaceV3.model_validate(migrated_payload)
        except ValidationError as error:
            issues = [
                f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
                for item in error.errors(include_url=False)
            ]
            raise ValueError("Invalid study workspace: " + "; ".join(issues)) from error
        workspace = validated.model_dump(mode="json", exclude={"id", "revision", "saved_at"})
        workspace["saved_at"] = datetime.now(timezone.utc).isoformat()
        return workspace
    if payload.get("version") != 1:
        raise ValueError("Unsupported study workspace version")
    allowed_v1_fields = {
        "format",
        "version",
        "id",
        "revision",
        "saved_at",
        "deleted_at",
        "study_name",
        "source_file_name",
        "analysis_time",
        "columns",
        "rows",
        "settings",
        "result",
    }
    unknown_fields = set(payload) - allowed_v1_fields
    if unknown_fields:
        raise ValueError(f"Unknown v1 study workspace field: {sorted(unknown_fields)[0]}")
    if not isinstance(payload.get("study_name"), str) or not payload["study_name"].strip():
        raise ValueError("study_name must be a non-empty string")
    if len(payload["study_name"]) > 200:
        raise ValueError("study_name must be at most 200 characters")
    if not isinstance(payload.get("source_file_name"), str):
        raise ValueError("source_file_name must be a string")
    if len(payload["source_file_name"]) > 255:
        raise ValueError("source_file_name must be at most 255 characters")
    deleted_at = payload.get("deleted_at")
    if deleted_at is not None:
        if not isinstance(deleted_at, str):
            raise ValueError("deleted_at must be a timezone-aware timestamp")
        try:
            parsed_deleted_at = datetime.fromisoformat(deleted_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("deleted_at must be a valid ISO timestamp") from error
        if parsed_deleted_at.utcoffset() is None:
            raise ValueError("deleted_at must include a timezone")
    columns = payload.get("columns")
    if (
        not isinstance(columns, list)
        or not columns
        or len(columns) > MAX_COLUMN_COUNT
        or any(not isinstance(column, str) for column in columns)
    ):
        raise ValueError(f"columns must be a list of at most {MAX_COLUMN_COUNT} strings")
    if any(not column or column != column.strip() for column in columns):
        raise ValueError("columns must be non-empty and already trimmed")
    if len(set(columns)) != len(columns):
        raise ValueError("columns must not contain duplicate names")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows or len(rows) > MAX_ROW_COUNT:
        raise ValueError(f"rows must be a list of at most {MAX_ROW_COUNT:,} measurements")
    if any(
        not isinstance(row, dict)
        or any(not isinstance(key, str) or not key for key in row)
        or any(not isinstance(value, str) for value in row.values())
        for row in rows
    ):
        raise ValueError("rows must contain scalar column values")
    column_set = set(columns)
    if any(set(row) != column_set for row in rows):
        raise ValueError("each row must contain exactly the named columns")
    settings = payload.get("settings", {})
    if not isinstance(settings, dict) or any(not isinstance(key, str) for key in settings):
        raise ValueError("settings must be an object")
    if any(not _is_json_scalar(value) for value in settings.values()):
        raise ValueError("settings must contain finite scalar values")
    result = payload.get("result")
    if not _validated_analysis_result(result):
        raise ValueError("result must contain a valid tensile analysis summary and points")
    width = settings.get("widthMm")
    thickness = settings.get("thicknessMm")
    gauge_length = settings.get("gaugeLengthMm")
    try:
        if any(isinstance(value, bool) for value in (width, thickness, gauge_length)):
            raise ValueError("boolean dimension")
        known_width = float(width) if width not in (None, "") else None
        known_thickness = float(thickness) if thickness not in (None, "") else None
        known_gauge = float(gauge_length) if gauge_length not in (None, "") else None
    except (TypeError, ValueError) as error:
        raise ValueError("specimen dimensions must be numeric") from error
    if any(
        value is not None and (not math.isfinite(value) or value <= 0)
        for value in (known_width, known_thickness, known_gauge)
    ):
        raise ValueError("specimen dimensions must be finite and positive")
    if result is not None:
        if result["summary"]["sample_count"] != len(rows):
            raise ValueError("result sample count must match the measurement row count")
        summary = result["summary"]
        if (
            known_width is not None
            and known_thickness is not None
            and not math.isclose(
                summary["cross_section_area_mm2"], known_width * known_thickness, rel_tol=1e-9
            )
        ):
            raise ValueError("result area does not match the saved specimen dimensions")
        if known_gauge is not None and not math.isclose(
            summary["gauge_length_mm"], known_gauge, rel_tol=1e-9
        ):
            raise ValueError("result gauge length does not match the saved specimen dimensions")
    analysis_time = payload.get("analysis_time", "")
    if not isinstance(analysis_time, str):
        raise ValueError("analysis_time must be a timestamp string")
    if analysis_time:
        try:
            parsed_analysis_time = datetime.fromisoformat(analysis_time.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("analysis_time must be a valid ISO timestamp") from error
        if parsed_analysis_time.utcoffset() is None:
            raise ValueError("analysis_time must include a timezone")
    return {
        "format": "styrkeanalyse-fdm-study",
        "version": 1,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "analysis_time": analysis_time,
        "study_name": payload["study_name"].strip(),
        "source_file_name": payload["source_file_name"],
        "columns": columns,
        "rows": rows,
        "settings": settings,
        "result": result,
    }


def _workspace_measurement_count(workspace: dict[str, Any]) -> int:
    if workspace.get("version") in {2, 3}:
        return sum(
            len(test_run["rows"])
            for specimen in workspace["specimens"]
            for test_run in specimen["test_runs"]
        )
    return len(workspace["rows"])


def _load_saved_study(path: Path) -> dict[str, Any]:
    try:
        study = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Could not read the saved study") from error
    if not isinstance(study, dict):
        raise ValueError("Saved study must be a JSON object")
    _validated_workspace(study)
    _revision(study)
    if study.get("id") != path.stem:
        raise ValueError("Saved study ID does not match its storage path")
    study.setdefault("revision", 1)
    return study


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

    def _send_json(
        self, status: int, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

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

    def _proxy_runner(self, method: str, path: str, body: bytes | None = None) -> None:
        runner_url = os.environ.get("FDM_RUNNER_URL", "http://runner:8020").rstrip("/")
        headers = {"Accept": "application/json, application/octet-stream"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(runner_url + path, data=body, headers=headers, method=method)
        try:
            with urlopen(
                request, timeout=float(os.environ.get("FDM_RUNNER_TIMEOUT", "180"))
            ) as response:
                self._send_bytes(
                    response.status,
                    response.read(),
                    response.headers.get("Content-Type", "application/octet-stream"),
                )
        except HTTPError as error:
            self._send_bytes(
                error.code,
                error.read(),
                error.headers.get("Content-Type", "application/json; charset=utf-8"),
            )
        except (URLError, TimeoutError, OSError) as error:
            LOGGER.warning("Runner request failed: %s", error)
            self._send_json(503, {"error": "The scientific runner is unavailable"})

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

    def _require_if_match(self, study: dict[str, Any]) -> bool:
        header = self.headers.get("If-Match")
        if header is None:
            self._send_json(428, {"error": "Send the current study revision in If-Match"})
            return False
        expected = _expected_revision(header)
        if expected is None:
            self._send_json(400, {"error": "If-Match must contain a study revision"})
            return False
        current = _revision(study)
        if expected != current:
            self._send_json(
                409,
                {
                    "error": (
                        "This study changed on another device. Keep the draft and "
                        "reload or save it as a copy."
                    ),
                    "current_revision": current,
                    "current_saved_at": study.get("saved_at", ""),
                },
                {"ETag": _etag(current)},
            )
            return False
        return True

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
        if path == "/api/retention":
            try:
                days = _retention_days(self.data_root)
            except ValueError as error:
                self._send_json(500, {"error": str(error)})
                return
            self._send_json(
                200,
                {
                    "retention_days": days,
                    "minimum_days": MIN_RETENTION_DAYS,
                    "maximum_days": MAX_RETENTION_DAYS,
                },
            )
            return
        if path == "/api/studies":
            try:
                with STUDY_LOCK:
                    _purge_expired_studies(self.data_root)
                    studies = []
                    for study_path in (self.data_root / "studies").glob("*.json"):
                        try:
                            study = _load_saved_study(study_path)
                            if study.get("deleted_at"):
                                continue
                            if study.get("version") in {2, 3}:
                                tests = [
                                    test_run
                                    for specimen in study["specimens"]
                                    for test_run in specimen["test_runs"]
                                ]
                                source_file_name = (
                                    tests[0]["input_file"]["filename"] if tests else ""
                                )
                                analysis_time = tests[0].get("analysis_time", "") if tests else ""
                            else:
                                source_file_name = study["source_file_name"]
                                analysis_time = study.get("analysis_time", "")
                            studies.append(
                                {
                                    "id": study["id"],
                                    "revision": _revision(study),
                                    "study_name": study["study_name"],
                                    "source_file_name": source_file_name,
                                    "saved_at": study["saved_at"],
                                    "analysis_time": analysis_time,
                                }
                            )
                        except (OSError, KeyError, ValueError, TypeError, AttributeError):
                            LOGGER.exception("Skipping invalid saved study at %s", study_path)
                            continue
            except ValueError as error:
                self._send_json(500, {"error": str(error)})
                return
            studies.sort(key=lambda item: item["saved_at"], reverse=True)
            self._send_json(200, {"studies": studies})
            return
        if path == "/api/trash":
            try:
                with STUDY_LOCK:
                    retention_days = _retention_days(self.data_root)
                    _purge_expired_studies(self.data_root)
                    studies = []
                    for study_path in (self.data_root / "studies").glob("*.json"):
                        try:
                            study = _load_saved_study(study_path)
                            deleted_at = study.get("deleted_at")
                            if not deleted_at:
                                continue
                            if study.get("version") in {2, 3}:
                                tests = [
                                    test_run
                                    for specimen in study["specimens"]
                                    for test_run in specimen["test_runs"]
                                ]
                                source_file_name = (
                                    tests[0]["input_file"]["filename"] if tests else ""
                                )
                            else:
                                source_file_name = study["source_file_name"]
                            deleted_time = datetime.fromisoformat(deleted_at.replace("Z", "+00:00"))
                            studies.append(
                                {
                                    "id": study["id"],
                                    "revision": _revision(study),
                                    "study_name": study["study_name"],
                                    "source_file_name": source_file_name,
                                    "saved_at": study["saved_at"],
                                    "deleted_at": deleted_at,
                                    "expires_at": (
                                        deleted_time + timedelta(days=retention_days)
                                    ).isoformat(),
                                }
                            )
                        except (OSError, KeyError, ValueError, TypeError, AttributeError):
                            LOGGER.exception("Skipping invalid trashed study at %s", study_path)
                    studies.sort(key=lambda item: item["deleted_at"], reverse=True)
            except ValueError as error:
                self._send_json(500, {"error": str(error)})
                return
            self._send_json(200, {"studies": studies, "retention_days": retention_days})
            return
        if path.startswith("/api/studies/"):
            study_id = _study_id(path)
            study_path = self._study_file(study_id) if study_id else None
            if study_path is None:
                self._send_json(400, {"error": "Invalid study ID"})
                return
            try:
                with STUDY_LOCK:
                    study = _load_saved_study(study_path)
            except FileNotFoundError:
                self._send_json(404, {"error": "Study not found"})
            except (OSError, ValueError):
                LOGGER.exception("Could not read saved study %s", study_id)
                self._send_json(500, {"error": "Could not read or validate the saved study"})
            else:
                if study.get("deleted_at"):
                    self._send_json(410, {"error": "Study is in trash. Restore it before opening."})
                else:
                    revision = _revision(study)
                    self._send_json(200, study, {"ETag": _etag(revision)})
            return
        job_match = JOB_PATH.fullmatch(path)
        if job_match:
            self._proxy_runner("GET", path)
            return
        run_match = RUN_PATH.fullmatch(path)
        if run_match:
            self._proxy_runner("GET", path)
            return
        artifact_match = ARTIFACT_PATH.fullmatch(path)
        if artifact_match:
            self._proxy_runner("GET", path)
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
                workspace["revision"] = 1
                with STUDY_LOCK:
                    self._save_study(study_id, workspace)
            except OSError:
                LOGGER.exception("Failed to save study %s", study_id)
                self._send_json(500, {"error": "Desktop study storage is unavailable"})
                return
            LOGGER.info(
                "Saved study %s with %s measurement rows",
                study_id,
                _workspace_measurement_count(workspace),
            )
            self._send_json(
                201,
                {"id": study_id, "revision": 1, "saved_at": workspace["saved_at"]},
                {"ETag": _etag(1)},
            )
            return
        action = _study_action(path)
        if action is not None and action[1] == "restore":
            study_id, _ = action
            with STUDY_LOCK:
                try:
                    _purge_expired_studies(self.data_root)
                    study = _load_saved_study(self._study_file(study_id))
                except FileNotFoundError:
                    self._send_json(404, {"error": "Study not found or retention expired"})
                    return
                except ValueError as error:
                    self._send_json(500, {"error": str(error)})
                    return
                if not study.get("deleted_at"):
                    self._send_json(409, {"error": "Study is not in trash"})
                    return
                if not self._require_if_match(study):
                    return
                revision = _revision(study) + 1
                study.pop("deleted_at", None)
                study["revision"] = revision
                study["saved_at"] = datetime.now(timezone.utc).isoformat()
                try:
                    self._save_study(study_id, study)
                except OSError:
                    self._send_json(500, {"error": "Desktop study storage is unavailable"})
                    return
            self._send_json(200, {"id": study_id, "revision": revision}, {"ETag": _etag(revision)})
            return
        if path == "/api/runs" or RUN_REPLAY_PATH.fullmatch(path):
            payload = self._read_json_object()
            if payload is None:
                return
            self._proxy_runner(
                "POST",
                path,
                json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            )
            return
        self._send_json(404, {"error": "API route not found"})

    def do_PUT(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/retention":
            payload = self._read_json_object()
            if payload is None:
                return
            days = payload.get("retention_days")
            if (
                isinstance(days, bool)
                or not isinstance(days, int)
                or not MIN_RETENTION_DAYS <= days <= MAX_RETENTION_DAYS
            ):
                self._send_json(
                    400,
                    {
                        "error": (
                            f"retention_days must be an integer from {MIN_RETENTION_DAYS} "
                            f"to {MAX_RETENTION_DAYS}"
                        )
                    },
                )
                return
            try:
                with STUDY_LOCK:
                    _write_json_atomically(
                        _retention_path(self.data_root), {"retention_days": days}
                    )
                    _purge_expired_studies(self.data_root)
            except (OSError, ValueError):
                LOGGER.exception("Could not update study retention policy")
                self._send_json(500, {"error": "Could not update the study retention policy"})
                return
            self._send_json(200, {"retention_days": days})
            return
        study_id = _study_id(path)
        if study_id is None:
            self._send_json(404, {"error": "Study route not found"})
            return
        payload = self._read_json_object()
        if payload is None:
            return
        try:
            workspace = _validated_workspace(payload)
        except ValueError as error:
            self._send_json(400, {"error": str(error)})
            return
        with STUDY_LOCK:
            try:
                study = _load_saved_study(self._study_file(study_id))
            except FileNotFoundError:
                self._send_json(404, {"error": "Study not found"})
                return
            except ValueError as error:
                LOGGER.exception("Could not validate saved study %s", study_id)
                self._send_json(500, {"error": str(error)})
                return
            if study.get("deleted_at"):
                self._send_json(410, {"error": "Study is in trash. Restore it before saving."})
                return
            if not self._require_if_match(study):
                return
            revision = _revision(study) + 1
            workspace["revision"] = revision
            try:
                self._save_study(study_id, workspace)
            except OSError:
                LOGGER.exception("Failed to update study %s", study_id)
                self._send_json(500, {"error": "Desktop study storage is unavailable"})
                return
        LOGGER.info(
            "Updated study %s with %s measurement rows",
            study_id,
            _workspace_measurement_count(workspace),
        )
        self._send_json(
            200,
            {"id": study_id, "revision": revision, "saved_at": workspace["saved_at"]},
            {"ETag": _etag(revision)},
        )

    def do_DELETE(self) -> None:
        path = urlsplit(self.path).path
        action_path = _study_action(path)
        if action_path is None:
            study_id = _study_id(path)
            action = "trash"
        else:
            study_id, action = action_path
        if study_id is None:
            self._send_json(404, {"error": "Study route not found"})
            return
        with STUDY_LOCK:
            try:
                _purge_expired_studies(self.data_root)
                study = _load_saved_study(self._study_file(study_id))
            except FileNotFoundError:
                self._send_json(404, {"error": "Study not found or retention expired"})
                return
            except ValueError as error:
                self._send_json(500, {"error": str(error)})
                return
            if action == "trash" and study.get("deleted_at"):
                self._send_json(410, {"error": "Study is already in trash"})
                return
            if action == "permanent" and not study.get("deleted_at"):
                self._send_json(
                    409, {"error": "Move this study to trash before permanent deletion"}
                )
                return
            if not self._require_if_match(study):
                return
            current_revision = _revision(study)
            if action == "permanent":
                try:
                    self._study_file(study_id).unlink()
                except OSError:
                    self._send_json(500, {"error": "Could not permanently delete the study"})
                    return
                self.send_response(204)
                self.send_header("ETag", _etag(current_revision))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            revision = current_revision + 1
            study["deleted_at"] = datetime.now(timezone.utc).isoformat()
            study["saved_at"] = study["deleted_at"]
            study["revision"] = revision
            try:
                self._save_study(study_id, study)
            except OSError:
                self._send_json(500, {"error": "Could not move the study to trash"})
                return
        self._send_json(
            200,
            {"id": study_id, "revision": revision, "deleted_at": study["deleted_at"]},
            {"ETag": _etag(revision)},
        )


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
