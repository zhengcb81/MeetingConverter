"""MeetingConverter's public, offline feedback-control port."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

from core.feedback import feedback_io_path

OWNER = "meeting-converter"
PUBLICATION = "mc-publication/1"
GENERATION = "publication-v1"
ACTIONS = ("triage", "repair", "replay", "report")
IDENTITY = ("owner", "origin_owner", "run_id", "attempt_id", "step_id", "check_id")
HEX = re.compile(r"[a-f0-9]{64}")
ROLES = {"original", "translated", "bilingual"}
STALE_OUTPUTS = {"previous_translations_only", "stale_and_missing_translations"}
SUCCEEDED = {"published_current", "published_incomplete", "reused_existing", "published_degraded"}
FAILED = {"published_partial", "write_failed", "transcription_failed", "translation_failed"}


def _json(value, *, ascii_only=True):
    return json.dumps(value, ensure_ascii=ascii_only, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode("ascii")).hexdigest()


def _publication_version(body):
    return f"{PUBLICATION}/{_digest(body)}"


def _unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key")
        out[key] = value
    return out


def _key(value):
    return isinstance(value, str) and bool(HEX.fullmatch(value))


def _occurrence(row):
    if not isinstance(row, dict) or not all(isinstance(row.get(field), str) and row[field] for field in IDENTITY):
        return None
    if row["owner"] != OWNER or row["origin_owner"] != OWNER or row.get("schema_version") != "feedback-observation/1":
        return None
    return _digest([row[field] for field in IDENTITY])


def _validate(action, request):
    if not isinstance(request, dict):
        raise ValueError("expected request")
    key, body = request.get("action_id"), request.get("payload")
    method = "lookup" if action == "reconcile" else "submit"
    if (request.get("schema_version") != "feedback-action/1" or request.get("owner") != OWNER
            or request.get("method") != method or request.get("kind") != action or not _key(key)
            or not isinstance(body, dict) or request.get("request_digest") != _digest([OWNER, action, key, body])):
        raise ValueError("invalid action envelope")
    occurrence = body.get("occurrence_id")
    if action in ("triage", "reconcile"):
        scope = [occurrence]
    elif action == "repair":
        scope = [body.get("issue_ref"), body.get("generation")]
    else:
        scope = [occurrence, OWNER, body.get("issue_ref"), body.get("fixed_version")]
        if action == "report":
            scope.append(body.get("verdict"))
    if key != _digest([action, OWNER, *scope]):
        raise ValueError("invalid action scope")
    return key, body


def _rows(path):
    try:
        with feedback_io_path(path).open("rb") as stream:
            for line in stream:
                try:
                    value = json.loads(line, object_pairs_hook=_unique)
                except (ValueError, RecursionError):
                    continue
                if isinstance(value, dict):
                    yield value
    except OSError:
        return


def _find_details(path, terminal):
    found = terminal.get("details_ref")
    if not isinstance(found, str):
        return None
    for detail in _rows(path.with_name(path.name + ".details.jsonl")):
        if (detail.get("details_id"), detail.get("step_id"), detail.get("phase"), detail.get("schema_version")) != (
            found, terminal["step_id"], "finished", "meeting-converter-feedback-detail/1",
        ):
            continue
        payload = {key: value for key, value in detail.items() if key != "details_id"}
        expected = hashlib.sha256(_json(payload, ascii_only=False).encode("utf-8")).hexdigest()[:16]
        if found == "fb-" + expected:
            return payload
    return None


class OwnerRuntime:
    def __init__(self, db, sidecars, sidecar_dir):
        self.db = feedback_io_path(db)
        self.sidecars = sidecars
        self.sidecar_dirs = [sidecar_dir] if isinstance(sidecar_dir, Path) else sidecar_dir or []

    def _original(self, row, *, include_details=False):
        """Locate the exact occurrence and its sibling terminal, not an audio path."""
        scope = tuple(row[field] for field in IDENTITY[:-1])
        paths = list(self.sidecars)
        for directory in self.sidecar_dirs:
            paths.extend(path for path in feedback_io_path(directory).glob("*.jsonl")
                         if not path.name.endswith(".details.jsonl"))
        by_check, terminal_paths = {}, []
        for path in paths:
            for saved in _rows(path):
                saved.setdefault("origin_owner", saved.get("owner"))
                if tuple(saved.get(field) for field in IDENTITY[:-1]) != scope:
                    continue
                check = saved.get("check_id")
                if not isinstance(check, str):
                    continue
                if check in by_check and by_check[check] != saved:
                    return None, None, None
                by_check[check] = saved
                if check == "publication-outcome":
                    terminal_paths.append(path)
        original = by_check.get(row["check_id"])
        if original != row:
            return None, None, None
        terminal = by_check.get("publication-outcome")
        reference = original.get("evidence_ref")
        base_ref = "/".join(reference.split("/")[:2]) if isinstance(reference, str) else None
        if terminal is not None and (
            not isinstance(terminal.get("actual"), str)
            or terminal.get("schema_version") != original["schema_version"]
            or not base_ref or terminal.get("evidence_ref") != base_ref
            or not original.get("version") or terminal.get("version") != original["version"]
        ):
            terminal = None
        if include_details and terminal is not None:
            for path in terminal_paths:
                detail = _find_details(path, terminal)
                if detail is not None:
                    return original, terminal, detail
        return original, terminal, None

    @staticmethod
    def _get(connection, key):
        row = connection.execute("SELECT receipt FROM actions WHERE action_id = ?", (key,)).fetchone()
        return json.loads(row[0]) if row is not None else None

    def read(self, key):
        if not _key(key) or not self.db.is_file():
            return None
        uri = "file:" + quote(str(self.db.absolute()), safe="/") + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            return self._get(connection, key)

    def reconcile(self, body):
        row = body.get("observation")
        occurrence = _occurrence(row)
        if occurrence is None or occurrence != body.get("occurrence_id"):
            return {"state": "unknown"}
        original, terminal, _ = self._original(row)
        if original is None or not isinstance(original.get("evidence_ref"), str):
            return {"state": "unknown"}
        actual = terminal.get("actual") if terminal else None
        status = "succeeded" if actual in SUCCEEDED else "failed" if actual in FAILED else "unconfirmed"
        return {"state": "done", "result": {
            "status": "cost_unknown", "evidence_ref": original["evidence_ref"],
            "job_status": status, "cost_state": "unknown", "step_id": original["step_id"],
        }}

    def _triage(self, body):
        row = body.get("observation")
        occurrence = _occurrence(row)
        if occurrence is None or occurrence != body.get("occurrence_id"):
            return {"decision": "needs_evidence"}, None
        original, terminal, detail = self._original(row, include_details=True)
        if original is None:
            return {"decision": "needs_evidence"}, None
        # A writer can still be appending the terminal to the same sidecar.
        if original.get("issue_key") == "stale-output-success" and terminal is None:
            return None, None
        if original.get("disposition") == "expected":
            return {"decision": "expected"}, None
        if (original.get("issue_key") != "stale-output-success" or original["check_id"] != "requested-outputs"
                or original.get("disposition") != "deviation" or original.get("actual") not in STALE_OUTPUTS
                or terminal is None or terminal.get("actual") != "published_incomplete" or detail is None
                or original.get("details_ref") != terminal.get("details_ref")
                or detail.get("outcome") != "published_incomplete"):
            return {"decision": "needs_evidence"}, None
        publication = _publication(occurrence, original, detail)
        if publication is None:
            return {"decision": "needs_evidence"}, None
        return {"decision": "repair", "issue_ref": f"{PUBLICATION}/{occurrence}", "generation": GENERATION}, publication

    def _repair(self, connection, key, body):
        issue = body.get("issue_ref")
        prefix = PUBLICATION + "/"
        occurrence = issue[len(prefix):] if isinstance(issue, str) and issue.startswith(prefix) else None
        if not _key(occurrence) or body.get("generation") != GENERATION:
            return None, None
        triage = self._get(connection, _digest(["triage", OWNER, occurrence]))
        if not triage or triage["result"].get("issue_ref") != issue:
            return None, None
        publication = triage["publication"]
        return {"fixed_version": _publication_version(publication),
                "evidence_ref": f"{PUBLICATION}/{key}"}, publication

    def _replay(self, connection, body):
        row = body.get("observation")
        occurrence = _occurrence(row)
        issue, version = body.get("issue_ref"), body.get("fixed_version")
        if (occurrence is None or occurrence != body.get("occurrence_id") or issue != f"{PUBLICATION}/{occurrence}"
                or body.get("issue_owner") != OWNER or body.get("acquisition") != "reuse_only"
                or body.get("original_occurrence_id") != row.get("original_occurrence_id", occurrence)):
            return None
        triage = self._get(connection, _digest(["triage", OWNER, occurrence]))
        repaired = self._get(connection, _digest(["repair", OWNER, issue, GENERATION]))
        if (not triage or not repaired or repaired["result"]["fixed_version"] != version
                or triage["request"]["payload"].get("observation") != row):
            return {"verdict": "unknown"}
        publication = repaired["publication"]
        verified = publication == triage["publication"] and version == _publication_version(publication)
        return {"verdict": "verified" if verified else "regressed", "verified_version": version,
                "evidence_ref": repaired["result"]["evidence_ref"]}

    def _report(self, connection, body):
        occurrence = body.get("occurrence_id")
        issue, version = body.get("issue_ref"), body.get("fixed_version")
        prior = self._get(connection, _digest(["replay", OWNER, occurrence, OWNER, issue, version]))
        if not prior or body.get("origin_owner") != OWNER or body.get("verdict") not in ("verified", "regressed"):
            return None
        result = prior["result"]
        if (result.get("verified_version") != version or result.get("verdict") != body["verdict"]
                or result.get("evidence_ref") != body.get("evidence_ref")
                or prior["request"]["payload"].get("original_occurrence_id") != body.get("original_occurrence_id")):
            return None
        return {"recorded": True}

    def dispatch(self, action, request):
        key, body = _validate(action, request)
        if action == "reconcile":
            return self.reconcile(body)
        self.db.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db, timeout=20)) as connection, connection:
            connection.execute("CREATE TABLE IF NOT EXISTS actions (action_id TEXT PRIMARY KEY, receipt TEXT NOT NULL)")
            connection.execute("BEGIN IMMEDIATE")
            saved = self._get(connection, key)
            if saved is not None:
                if _digest(saved["request"]) != _digest(request):
                    raise ValueError("conflicting action request")
                return {"result": saved["result"]}

            publication = None
            if action == "triage":
                result, publication = self._triage(body)
            elif action == "repair":
                result, publication = self._repair(connection, key, body)
            elif action == "replay":
                result = self._replay(connection, body)
            else:
                result = self._report(connection, body)
            if result is None:
                return {"state": "unknown"}
            receipt = {"request": request, "result": result}
            if publication is not None:
                receipt["publication"] = publication
            connection.execute("INSERT INTO actions VALUES (?, ?)", (key, _json(receipt)))
            return {"result": result}


def _publication(occurrence, row, detail):
    current, retained, missing, seen = {}, [], [], set()
    events = detail.get("writers")
    if not isinstance(events, list):
        return None
    for event in events:
        if not isinstance(event, dict):
            return None
        role, outcome = event.get("role"), event.get("result")
        if not isinstance(role, str) or role not in ROLES or role in seen:
            return None
        seen.add(role)
        if outcome == "committed_this_round" and event.get("this_round") is True:
            sha, size = event.get("sha256"), event.get("bytes")
            if (event.get("fingerprint_source") != "committed_writer"
                    or not _key(sha) or type(size) is not int or size < 0):
                return None
            current[role] = {"sha256": sha, "bytes": size}
        elif outcome in ("previous_kept", "absent") and event.get("this_round") is False:
            (retained if outcome == "previous_kept" else missing).append(role)
        else:
            return None
    actual = "stale_and_missing_translations" if missing else "previous_translations_only"
    if seen != ROLES or set(current) != {"original"} or not retained or actual != row["actual"]:
        return None
    return {"schema_version": PUBLICATION, "occurrence_id": occurrence, "step_id": row["step_id"],
            "source_evidence": row.get("evidence_ref"), "publication_outcome": "published_incomplete",
            "current": current, "retained": sorted(retained), "missing": sorted(missing)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--sidecar", action="append", type=Path, default=[])
    parser.add_argument("--sidecar-dir", action="append", type=Path, default=[])
    commands = parser.add_subparsers(dest="action", required=True)
    for action in (*ACTIONS, "reconcile"):
        commands.add_parser(action)
    for action in ("get-action", "get-publication"):
        commands.add_parser(action).add_argument("action_id")
    args = parser.parse_args(argv)
    owner = OwnerRuntime(args.db, args.sidecar, args.sidecar_dir)
    try:
        if args.action.startswith("get-"):
            receipt = owner.read(args.action_id)
            payload = {}
            if receipt is not None:
                if args.action == "get-action":
                    payload = {"receipt": {name: receipt[name] for name in ("request", "result")}}
                elif receipt["request"]["kind"] == "repair":
                    publication = receipt.get("publication")
                    if publication is not None and _publication_version(publication) == receipt["result"].get("fixed_version"):
                        payload = {"publication": publication}
        else:
            payload = owner.dispatch(args.action, json.load(sys.stdin, object_pairs_hook=_unique))
        print(_json(payload))
    except (ValueError, OSError, sqlite3.Error, RecursionError) as error:
        print(_json({"state": "unknown", "error_type": type(error).__name__}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
