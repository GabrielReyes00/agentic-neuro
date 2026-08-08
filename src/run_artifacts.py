#!/usr/bin/env python3
"""Manifest and retention planning for workflow-owned runtime artifacts."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from io_utils import atomic_write_json
    from runtime_paths import RUNTIME_DIR
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from .io_utils import atomic_write_json
    from .runtime_paths import RUNTIME_DIR


MANIFEST_SCHEMA_VERSION = 2
RUNS_DIRNAME = "runs"
MANIFEST_NAME = "run_manifest.json"
TERMINAL_STATUSES = frozenset({"completed", "failed", "abandoned"})
VALID_STATUSES = frozenset({"initialized", "running", *TERMINAL_STATUSES})
VALID_RETENTION = frozenset({"transient", "audit", "deliverable", "cache"})
VALID_TRANSITIONS = {
    "initialized": frozenset({"running", "failed", "abandoned"}),
    "running": TERMINAL_STATUSES,
    "completed": frozenset(),
    "failed": frozenset(),
    "abandoned": frozenset(),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not slug:
        raise ValueError("workflow and run identifiers must contain a letter or number")
    return slug


def _contained(path: Path, root: Path) -> Path:
    resolved_root = root.expanduser().resolve()
    resolved = path.expanduser().resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"runtime path escapes configured root: {path}")
    return resolved


def run_directory(workflow: str, run_id: str, *, root: Path = RUNTIME_DIR) -> Path:
    return _contained(root / RUNS_DIRNAME / _slug(workflow) / _slug(run_id), root)


def _manifest_path(run_dir: Path) -> Path:
    return run_dir / MANIFEST_NAME


def load_manifest(run_dir: Path, *, root: Path = RUNTIME_DIR) -> dict[str, Any]:
    path = _manifest_path(_contained(run_dir, root))
    payload = json.loads(path.read_text(encoding="utf-8"))
    if int(payload.get("schema_version", 0)) != MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"unsupported run manifest schema: {payload.get('schema_version')}")
    return payload


def start_run(
    workflow: str,
    run_id: str,
    *,
    title: str = "",
    workflow_state: dict[str, Any] | None = None,
    root: Path = RUNTIME_DIR,
) -> dict[str, Any]:
    run_dir = run_directory(workflow, run_id, root=root)
    manifest_path = _manifest_path(run_dir)
    if manifest_path.exists():
        raise FileExistsError(f"run already exists: {run_dir}")
    created_at = _utc_now()
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "run_id": _slug(run_id),
        "workflow": _slug(workflow),
        "title": title.strip(),
        "status": "initialized",
        "created_at": created_at,
        "updated_at": created_at,
        "artifacts": [],
        "failure": "",
        "workflow_state": dict(workflow_state or {}),
    }
    atomic_write_json(manifest_path, payload)
    return {"run_dir": str(run_dir), "manifest": payload}


def update_workflow_state(
    run_dir: Path,
    workflow_state: dict[str, Any],
    *,
    root: Path = RUNTIME_DIR,
) -> dict[str, Any]:
    run_dir = _contained(run_dir, root)
    payload = load_manifest(run_dir, root=root)
    payload["workflow_state"] = dict(workflow_state)
    payload["updated_at"] = _utc_now()
    atomic_write_json(_manifest_path(run_dir), payload)
    return payload


def transition_run(
    run_dir: Path,
    status: str,
    *,
    failure: str = "",
    root: Path = RUNTIME_DIR,
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid run status: {status}")
    run_dir = _contained(run_dir, root)
    payload = load_manifest(run_dir, root=root)
    current = str(payload["status"])
    if status != current and status not in VALID_TRANSITIONS[current]:
        raise ValueError(f"invalid run transition: {current} -> {status}")
    payload["status"] = status
    payload["updated_at"] = _utc_now()
    payload["failure"] = failure.strip() if status == "failed" else ""
    atomic_write_json(_manifest_path(run_dir), payload)
    return payload


def register_artifact(
    run_dir: Path,
    artifact: Path,
    *,
    role: str,
    retention: str,
    root: Path = RUNTIME_DIR,
) -> dict[str, Any]:
    if retention not in VALID_RETENTION:
        raise ValueError(f"invalid retention class: {retention}")
    run_dir = _contained(run_dir, root)
    artifact = _contained(artifact, run_dir)
    payload = load_manifest(run_dir, root=root)
    relative = str(artifact.relative_to(run_dir))
    record = {
        "path": relative,
        "role": role.strip(),
        "retention": retention,
        "exists": artifact.is_file(),
        "size_bytes": artifact.stat().st_size if artifact.is_file() else 0,
    }
    artifacts = [item for item in payload["artifacts"] if item.get("path") != relative]
    artifacts.append(record)
    payload["artifacts"] = sorted(artifacts, key=lambda item: item["path"])
    payload["updated_at"] = _utc_now()
    atomic_write_json(_manifest_path(run_dir), payload)
    return record


def audit_runtime(root: Path = RUNTIME_DIR) -> dict[str, Any]:
    root = root.expanduser().resolve()
    if not root.is_dir():
        return {"root": str(root), "files": 0, "bytes": 0, "managed_runs": 0, "legacy_files": 0}
    files = [path for path in root.rglob("*") if path.is_file()]
    managed_root = root / RUNS_DIRNAME
    manifests = list(managed_root.glob(f"*/*/{MANIFEST_NAME}")) if managed_root.is_dir() else []
    legacy = [path for path in files if managed_root not in path.parents]
    statuses: dict[str, int] = {}
    invalid_manifests: list[str] = []
    for path in manifests:
        try:
            status = str(json.loads(path.read_text(encoding="utf-8")).get("status", "unknown"))
            statuses[status] = statuses.get(status, 0) + 1
        except (OSError, ValueError):
            invalid_manifests.append(str(path.relative_to(root)))
    return {
        "root": str(root),
        "files": len(files),
        "bytes": sum(path.stat().st_size for path in files),
        "managed_runs": len(manifests),
        "managed_statuses": dict(sorted(statuses.items())),
        "invalid_manifests": invalid_manifests,
        "legacy_files": len(legacy),
        "legacy_bytes": sum(path.stat().st_size for path in legacy),
    }


def retention_plan(
    *,
    root: Path = RUNTIME_DIR,
    older_than_days: int = 30,
) -> dict[str, Any]:
    """Return eligible transient paths; never delete files."""
    root = root.expanduser().resolve()
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(0, older_than_days))
    candidates: list[dict[str, Any]] = []
    managed_root = root / RUNS_DIRNAME
    for manifest_path in managed_root.glob(f"*/*/{MANIFEST_NAME}") if managed_root.is_dir() else ():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            updated = datetime.fromisoformat(str(payload["updated_at"]))
        except (OSError, ValueError, KeyError):
            continue
        if payload.get("status") not in TERMINAL_STATUSES or updated > cutoff:
            continue
        run_dir = manifest_path.parent
        for artifact in payload.get("artifacts", []):
            if artifact.get("retention") != "transient":
                continue
            candidate = _contained(run_dir / str(artifact.get("path", "")), run_dir)
            if candidate.is_file():
                candidates.append(
                    {
                        "run": str(run_dir.relative_to(root)),
                        "path": str(candidate.relative_to(root)),
                        "size_bytes": candidate.stat().st_size,
                    }
                )
    return {
        "older_than_days": older_than_days,
        "candidate_count": len(candidates),
        "candidate_bytes": sum(item["size_bytes"] for item in candidates),
        "candidates": candidates,
        "applied": False,
    }


def prune_run_transients(
    run_dir: Path,
    *,
    apply: bool = False,
    root: Path = RUNTIME_DIR,
) -> dict[str, Any]:
    """Plan or remove only registered transient files from one terminal run."""
    run_dir = _contained(run_dir, root)
    payload = load_manifest(run_dir, root=root)
    if payload.get("status") not in TERMINAL_STATUSES:
        raise ValueError("transient pruning requires a terminal run")
    candidates: list[dict[str, Any]] = []
    for artifact in payload.get("artifacts", []):
        if artifact.get("retention") != "transient":
            continue
        candidate = _contained(run_dir / str(artifact.get("path", "")), run_dir)
        if not candidate.is_file():
            continue
        candidates.append(
            {
                "path": str(candidate.relative_to(run_dir)),
                "size_bytes": candidate.stat().st_size,
            }
        )
        if apply:
            candidate.unlink()
            artifact["exists"] = False
            artifact["size_bytes"] = 0
            artifact["pruned_at"] = _utc_now()
    if apply and candidates:
        payload["updated_at"] = _utc_now()
        atomic_write_json(_manifest_path(run_dir), payload)
    return {
        "run": str(run_dir.relative_to(root.expanduser().resolve())),
        "candidate_count": len(candidates),
        "candidate_bytes": sum(item["size_bytes"] for item in candidates),
        "candidates": candidates,
        "applied": apply,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("--workflow", required=True)
    start.add_argument("--run-id", required=True)
    start.add_argument("--title", default="")
    transition = subparsers.add_parser("transition")
    transition.add_argument("--run-dir", type=Path, required=True)
    transition.add_argument("--status", choices=sorted(VALID_STATUSES), required=True)
    transition.add_argument("--failure", default="")
    register = subparsers.add_parser("register")
    register.add_argument("--run-dir", type=Path, required=True)
    register.add_argument("--artifact", type=Path, required=True)
    register.add_argument("--role", required=True)
    register.add_argument("--retention", choices=sorted(VALID_RETENTION), required=True)
    subparsers.add_parser("audit")
    plan = subparsers.add_parser("plan-prune")
    plan.add_argument("--older-than-days", type=int, default=30)
    prune = subparsers.add_parser("prune")
    prune.add_argument("--run-dir", type=Path, required=True)
    prune.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if args.command == "start":
        result = start_run(args.workflow, args.run_id, title=args.title)
    elif args.command == "transition":
        result = transition_run(args.run_dir, args.status, failure=args.failure)
    elif args.command == "register":
        result = register_artifact(
            args.run_dir,
            args.artifact,
            role=args.role,
            retention=args.retention,
        )
    elif args.command == "audit":
        result = audit_runtime()
    elif args.command == "plan-prune":
        result = retention_plan(older_than_days=args.older_than_days)
    else:
        result = prune_run_transients(args.run_dir, apply=args.apply)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
