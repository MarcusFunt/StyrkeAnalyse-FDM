"""Persistent mutable job state for asynchronous formal Run execution."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class RunJob(BaseModel):
    """A mutable execution handle that points to an immutable Run once complete."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    )
    operation: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    status: Literal["queued", "running", "succeeded", "failed"]
    created_at: datetime
    updated_at: datetime
    run_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    )
    replay_of_run_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    )
    error: str | None = Field(default=None, max_length=4000)

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("job timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def state_is_consistent(self) -> RunJob:
        if self.updated_at < self.created_at:
            raise ValueError("job updated_at cannot precede created_at")
        if self.status == "succeeded" and self.run_id is None:
            raise ValueError("a succeeded job must reference an immutable Run")
        if self.status == "failed" and not self.error:
            raise ValueError("a failed job must include an error")
        return self


class JobStore:
    """Atomic mutable job records, separate from create-only scientific Runs."""

    def __init__(self, data_root: str | Path):
        self.root = Path(data_root).resolve() / "jobs"
        self._lock = threading.RLock()

    def path_for(self, job_id: str) -> Path:
        try:
            canonical = str(uuid.UUID(job_id))
        except (ValueError, AttributeError, TypeError) as error:
            raise ValueError("job ID must be a UUID") from error
        if canonical != job_id:
            raise ValueError("job ID must use canonical lowercase UUID form")
        return self.root / f"{canonical}.json"

    def put(self, job: RunJob) -> None:
        target = self.path_for(job.id)
        payload = (
            json.dumps(
                job.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
        with self._lock:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=target.parent, prefix=f".{job.id}.", delete=False
                ) as temporary:
                    temporary_path = Path(temporary.name)
                    temporary.write(payload)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                os.replace(temporary_path, target)
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)

    def get(self, job_id: str) -> RunJob:
        path = self.path_for(job_id)
        try:
            return RunJob.model_validate_json(path.read_bytes())
        except FileNotFoundError:
            raise
        except (OSError, ValidationError, ValueError) as error:
            raise ValueError(f"invalid job record {job_id}") from error

    def fail_interrupted(self, *, now: datetime) -> int:
        """Fail queued/running jobs after process restart instead of pretending they resumed."""
        count = 0
        with self._lock:
            if not self.root.exists():
                return 0
            for path in self.root.glob("*.json"):
                try:
                    job = RunJob.model_validate_json(path.read_bytes())
                except (OSError, ValidationError, ValueError):
                    continue
                if job.status not in {"queued", "running"}:
                    continue
                self.put(
                    job.model_copy(
                        update={
                            "status": "failed",
                            "updated_at": now,
                            "error": "runner restarted before this job completed",
                        }
                    )
                )
                count += 1
        return count
