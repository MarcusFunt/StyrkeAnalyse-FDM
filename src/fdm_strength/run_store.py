"""Content-addressed artifact storage and create-only formal Run records."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path

from pydantic import ValidationError

from fdm_strength.run_models import ArtifactReference, Run


class ArtifactStore:
    def __init__(self, data_root: str | Path):
        self.root = Path(data_root).resolve() / "artifacts" / "sha256"

    def path_for(self, digest: str) -> Path:
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("artifact digest must be a lowercase SHA-256 hex value")
        return self.root / digest[:2] / digest

    def put_bytes(self, content: bytes, *, media_type: str) -> ArtifactReference:
        if not isinstance(content, bytes):
            raise TypeError("artifact content must be bytes")
        digest = hashlib.sha256(content).hexdigest()
        target = self.path_for(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            self._read_verified(target, digest)
        else:
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=target.parent, prefix=".artifact-", delete=False
                ) as temporary:
                    temporary_path = Path(temporary.name)
                    temporary.write(content)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                try:
                    os.link(temporary_path, target)
                except FileExistsError:
                    self._read_verified(target, digest)
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
        return ArtifactReference(
            sha256=digest,
            size_bytes=len(content),
            media_type=media_type,
        )

    def get_bytes(self, digest: str) -> bytes:
        target = self.path_for(digest)
        try:
            return self._read_verified(target, digest)
        except FileNotFoundError as error:
            raise FileNotFoundError(f"artifact {digest} was not found") from error

    @staticmethod
    def _read_verified(path: Path, expected_digest: str) -> bytes:
        content = path.read_bytes()
        actual_digest = hashlib.sha256(content).hexdigest()
        if actual_digest != expected_digest:
            raise ValueError(f"artifact {expected_digest} digest mismatch")
        return content


class RunStore:
    def __init__(self, data_root: str | Path):
        self.root = Path(data_root).resolve() / "runs"

    def path_for(self, run_id: str) -> Path:
        try:
            canonical_id = str(uuid.UUID(run_id))
        except (ValueError, AttributeError, TypeError) as error:
            raise ValueError("run ID must be a UUID") from error
        if canonical_id != run_id:
            raise ValueError("run ID must use canonical lowercase UUID form")
        return self.root / f"{canonical_id}.json"

    def create(self, run: Run) -> None:
        target = self.path_for(run.id)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            json.dumps(
                run.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=target.parent, prefix=".run-", delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            try:
                os.link(temporary_path, target)
            except FileExistsError as error:
                raise FileExistsError(f"run {run.id} is immutable and already exists") from error
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def get(self, run_id: str) -> Run:
        path = self.path_for(run_id)
        try:
            payload = path.read_bytes()
            run = Run.model_validate_json(payload)
        except FileNotFoundError:
            raise
        except (OSError, ValidationError, ValueError) as error:
            raise ValueError(f"invalid run record {run_id}") from error
        if run.id != run_id:
            raise ValueError(f"invalid run record {run_id}: record ID does not match path")
        return run
