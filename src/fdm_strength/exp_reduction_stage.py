"""CLI entrypoint for the pinned experimental-reduction runtime image."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from fdm_strength.experimental_reduction import analyze_uploaded_csv, reduce_campaign_workspace
from fdm_strength.stage_contract import load_stage_contract


def main() -> int:
    work_root = Path("/work")
    try:
        contract = load_stage_contract(work_root)
        inputs = {
            item.name: (work_root / "in" / item.name).read_bytes() for item in contract.inputs
        }
        if contract.operation == "tensile":
            source = inputs.get("source.csv")
            if source is None:
                raise ValueError("tensile stage requires source.csv")
            result = analyze_uploaded_csv(source, contract.parameters)
        elif contract.operation == "campaign":
            source = inputs.get("workspace.json")
            upstream_source = inputs.get("upstream-results.json")
            if source is None or upstream_source is None:
                raise ValueError(
                    "campaign stage requires workspace.json and upstream-results.json"
                )
            try:
                payload = json.loads(source)
                upstream_payload = json.loads(upstream_source)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("campaign inputs must be valid UTF-8 JSON") from error
            if not isinstance(payload, dict):
                raise ValueError("campaign workspace input must be a JSON object")
            if (
                not isinstance(upstream_payload, dict)
                or upstream_payload.get("schema_version") != 1
                or not isinstance(upstream_payload.get("runs"), dict)
            ):
                raise ValueError("campaign upstream result manifest is invalid")
            upstream_results: dict[str, dict[str, object]] = {}
            for run_id, entry in upstream_payload["runs"].items():
                if (
                    not isinstance(run_id, str)
                    or not isinstance(entry, dict)
                    or not isinstance(entry.get("result_artifact_sha256"), str)
                    or not isinstance(entry.get("specimen_reduction"), dict)
                ):
                    raise ValueError("campaign upstream result manifest contains an invalid entry")
                upstream_results[run_id] = {
                    "specimen_reduction": entry["specimen_reduction"]
                }
            result = reduce_campaign_workspace(payload, upstream_results)
        else:  # pragma: no cover - the stage registry prevents this
            raise ValueError(f"unsupported experimental-reduction operation {contract.operation}")

        output_bytes = (
            json.dumps(
                {"schema_version": 1, "run_id": contract.run_id, "result": result},
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        outputs = {
            "result.json": output_bytes,
        }
        if set(contract.expected_outputs) != {"result.json", "provenance.json"}:
            raise ValueError(
                "experimental-reduction stage requires result.json and provenance.json outputs"
            )
        provenance = {
            "schema_version": 1,
            "run_id": contract.run_id,
            "stage_id": contract.stage_id,
            "operation": contract.operation,
            "inputs": [
                {
                    "name": item.name,
                    "sha256": item.sha256,
                    "size_bytes": item.size_bytes,
                }
                for item in contract.inputs
            ],
            "outputs": [
                {
                    "name": name,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                }
                for name, content in outputs.items()
            ],
        }
        outputs["provenance.json"] = (
            json.dumps(
                provenance,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        for name, content in outputs.items():
            (work_root / "out" / name).write_bytes(content)
        return 0
    except (OSError, TypeError, ValueError) as error:
        print(f"experimental-reduction failed: {error}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
