"""Size synthetic V2 projection artifacts; never open Scout data or run a worker.

Reads the proposed DDL and literal observation text in repository tests. Builds
only private temporary SQLite fixtures. Results are capacity scenarios, not
production measurements, producer implementation, or routing parity tests.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import os
import platform
import resource
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
SCALES = (100000, 350000, 1000000, 2500000)


def fixture_texts():
    tree = ast.parse((ROOT / "test_router.py").read_text())
    texts = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "obs" and len(node.args) > 2
                and isinstance(node.args[2], ast.Constant)
                and isinstance(node.args[2].value, str)):
            texts.append(node.args[2].value)
    if not texts:
        raise ValueError("No literal observation fixtures found")
    return texts


def annotations():
    # A deliberately link-rich shape; these are synthetic opaque references.
    return json.dumps({
        "classification": "CONTROLLED_SAME_OPERATOR_VALIDATION",
        "same_operator": True, "independent_reputation": False,
        "operator_group": "fixture-local-operator",
        "capability_support": [{"capability_id": "software.debugging",
                                "classification": "producer-claim", "evidence_id": "fixture-evidence"}],
        "verification_links": [{"request_id": "FVR-83c180e9b05f85b0a72b",
                                "result_hash": "a" * 64, "bench_did": "did:key:z6MkFixtureBench",
                                "validation_id": "fixture-validation", "correctness": "PASS",
                                "reproducibility": "DETERMINISTIC", "authenticity": "UNVERIFIED",
                                "evidence_classification": "CONTROLLED_SAME_OPERATOR_VALIDATION"}],
        "task_routing_links": [{"job_proto": "a2a", "job_id": "job-123", "task_hash": "b" * 64,
                                 "routing_decision_id": "fixture-decision", "routing_decision_hash": "c" * 64}],
        "evidence_links": [{"room": "technocore", "generation": "0", "seq": 101,
                            "evidence_id": "fixture-evidence"}],
    }, sort_keys=True, separators=(",", ":"))


def build_fixture(ddl, texts, target_rows):
    # A mixed synthetic shape, not an assertion of production class frequencies.
    count = target_rows * 2 // 3
    edge_count = target_rows - count
    edge_ratio = edge_count / count
    text_floor = 0
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="router-v2-sizing-") as temporary:
        if shutil.disk_usage(temporary).free < count * 10000 + 2 * 1024**3:
            raise RuntimeError("Insufficient temporary free space for conservative fixture budget")
        path = Path(temporary) / "projection.sqlite"
        conn = sqlite3.connect(path)
        try:
            conn.execute("PRAGMA page_size=4096")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA cache_size=-16384")
            conn.execute("PRAGMA mmap_size=0")
            conn.execute("PRAGMA temp_store=FILE")
            conn.executescript(ddl)
            conn.execute("INSERT INTO snapshot_meta VALUES (1,?,?,?,?)",
                         ("scout-router-projection/v2", "1", "2026-09-08T00:00:00Z",
                          hashlib.sha256(json.dumps(selection_policy(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()))
            annotation = annotations()
            plain = json.dumps({"classification": None, "same_operator": None,
                                "independent_reputation": None, "operator_group": None,
                                "capability_support": [], "verification_links": [],
                                "task_routing_links": [], "evidence_links": []}, separators=(",", ":"))
            def membership(entity, row_id, rich):
                conn.execute("INSERT INTO selection_membership VALUES (?,?,?,?,?,?)", (
                    entity, row_id, "BENCH_VERIFICATION" if rich else "CONTEXT",
                    "2026-09-08T00:00:00Z", None if rich else "2026-10-08T00:00:00Z", "[]"))
            text_bytes = 0
            for number in range(count):
                text = texts[number % len(texts)]
                # Explicit synthetic long-text stress, not observed production lengths.
                text += "x" * max(0, text_floor - len(text.encode("utf-8")))
                normalized = " ".join(text.lower().split())
                text_bytes += len(text.encode("utf-8")) + len(normalized.encode("utf-8"))
                row_id = f"message-{number:012d}"
                digest = hashlib.sha256(f"fixture-{number}".encode()).hexdigest()
                signature = "A" * 86  # Sized placeholder, never asserted verified.
                payload = dict(room="technocore", generation="0", seq=number,
                               did="did:key:z6MkFixtureWorker", nonce=str(number),
                               sig=signature, text=text)
                message_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                raw_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
                conn.execute("INSERT INTO messages VALUES (" + ",".join("?" * 17) + ")", (
                    row_id, "technocore", "0", number, "2026-09-08T00:00:00Z",
                    "did:key:z6MkFixtureWorker", 1, text, normalized, digest,
                    str(number), signature, message_hash, "SIGNATURE_PRESENT_UNVERIFIED", digest,
                    "fixture-source-export", f"tc:technocore:0:{number}:{message_hash[:16]}"))
                # No real signature or raw hash is synthesized as verified evidence.
                conn.execute("INSERT INTO source_provenance VALUES (?,?,?,?,?,?,?,?)", (
                    "message", row_id, "fixture-scout", row_id, f"event-{number:012d}",
                    f"raw-{number:012d}", raw_hash, annotation if number % 10 == 0 else plain))
                membership("message", row_id, number % 10 == 0)
                if number % 5000 == 4999:
                    conn.commit()
            for number in range(edge_count):
                row_id = f"interaction-{number:012d}"
                conn.execute("INSERT INTO interactions VALUES (?,?,?,?,?)", (
                    row_id, "did:key:z6MkFixtureWorker", "did:key:z6MkFixtureBench", "reply", 1.0))
                conn.execute("INSERT INTO source_provenance VALUES (?,?,?,?,?,?,?,?)", (
                    "interaction", row_id, "fixture-scout", row_id, None, None, None,
                    annotation if number % 10 == 0 else plain))
                membership("interaction", row_id, number % 10 == 0)
                if number % 5000 == 4999:
                    conn.commit()
            conn.execute("INSERT INTO watermarks SELECT room,generation,COUNT(*),MIN(seq),MAX(seq) FROM messages GROUP BY room,generation")
            last = conn.execute("SELECT * FROM messages WHERE seq=?", (count - 1,))
            last_message = dict(zip([column[0] for column in last.description], last.fetchone()))
            witness_hash = hashlib.sha256(json.dumps(last_message, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
            conn.execute("INSERT INTO coverage_history VALUES (?,?,?,?,?)", (
                "technocore", "0", count - 1, f"message-{count-1:012d}", witness_hash))
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            construction_seconds = time.perf_counter() - started
            validation_started = time.perf_counter()
            if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("Fixture integrity failed")
            integrity_seconds = time.perf_counter() - validation_started
            page_count = conn.execute("PRAGMA page_count").fetchone()[0]
            page_size = conn.execute("PRAGMA page_size").fetchone()[0]
            index_bytes = conn.execute("SELECT COALESCE(SUM(d.pgsize),0) FROM dbstat AS d JOIN sqlite_master AS m ON m.name=d.name WHERE m.type='index'").fetchone()[0]
            logical_count = conn.execute("SELECT (SELECT COUNT(*) FROM messages)+(SELECT COUNT(*) FROM interactions)").fetchone()[0]
            provenance_count = conn.execute("SELECT COUNT(*) FROM source_provenance").fetchone()[0]
            membership_count = conn.execute("SELECT COUNT(*) FROM selection_membership").fetchone()[0]
            if logical_count != target_rows or provenance_count != logical_count or membership_count != logical_count:
                raise ValueError("Fixture row count mismatch")
            destination = Path(temporary) / "immutable.sqlite"
            backup_started = time.perf_counter()
            target = sqlite3.connect(destination)
            try:
                target.execute("PRAGMA cache_size=-16384")
                conn.backup(target, pages=256)
                target.execute("PRAGMA journal_mode=DELETE")
            finally:
                target.close()
            with destination.open("rb") as handle:
                os.fsync(handle.fileno())
            directory = os.open(temporary, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            backup_seconds = time.perf_counter() - backup_started
            digest = hashlib.sha256()
            hash_started = time.perf_counter()
            with destination.open("rb") as handle:
                if handle.read(20)[18:20] != b"\x01\x01":
                    raise ValueError("Backup is not standalone rollback-journal format")
                handle.seek(0)
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
            hash_seconds = time.perf_counter() - hash_started
            size = destination.stat().st_size
            if any(Path(str(destination) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
                raise ValueError("Backup left companions")
        finally:
            conn.close()
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak_bytes = peak if sys.platform == "darwin" else peak * 1024
        return {
            "requested_projected_evidence_rows": target_rows,
            "messages": count, "interactions": edge_count,
            "projected_evidence_rows": logical_count, "provenance_rows": provenance_count,
            "membership_rows": membership_count,
            "text_floor_bytes": text_floor, "edges_per_message": edge_ratio,
            "mean_combined_text_bytes": text_bytes / count,
            "rich_annotation_bytes": len(annotation.encode()),
            "plain_annotation_bytes": len(plain.encode()), "rich_annotation_fraction": 0.1,
            "closed_artifact_bytes": size, "page_count": page_count, "page_size": page_size,
            "index_bytes": index_bytes, "bytes_per_message_bundle": size / count,
            "bytes_per_projected_evidence_row": size / logical_count,
            "construction_seconds": construction_seconds, "integrity_seconds": integrity_seconds,
            "backup_seconds": backup_seconds, "sha256_seconds": hash_seconds,
            "artifact_sha256": digest.hexdigest(), "peak_process_rss_bytes": peak_bytes,
        }


def selection_policy():
    document = (ROOT / "docs/SCOUT_ROUTER_SNAPSHOT_V2.md").read_text()
    return json.loads(re.search(r"```json\n(.*?)\n```", document, re.S).group(1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scales", nargs="+", type=int, default=list(SCALES))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--child-scale", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    document = (ROOT / "docs/SCOUT_ROUTER_SNAPSHOT_V2.md").read_text()
    ddl = re.search(r"```sql\n(.*?)\n```", document, re.S).group(1)
    texts = fixture_texts()
    if args.child_scale is not None:
        if not 3 <= args.child_scale <= 2500000:
            parser.error("fixture scale must be in 3..2500000")
        print(json.dumps(build_fixture(ddl, texts, args.child_scale)))
        return
    results = []
    for count in args.scales:
        if not 3 <= count <= 2500000:
            parser.error("fixture scales must be in 3..2500000")
        print(f"Building and backing up {count:,} synthetic projected evidence rows", file=sys.stderr, flush=True)
        child = subprocess.run([sys.executable, "-B", __file__, "--child-scale", str(count)],
                               capture_output=True, text=True, check=True)
        result = json.loads(child.stdout)
        results.append(result)
        print(f"Finished {count:,}: {result['closed_artifact_bytes']:,} bytes", file=sys.stderr, flush=True)
    report = json.dumps({
        "schema": "router-projection-sizing-benchmark/v2",
        "sqlite_version": sqlite3.sqlite_version,
        "platform": platform.platform(), "python_version": platform.python_version(),
        "fixture_text_count": len(texts), "unique_fixture_texts": len(set(texts)),
        "fixture_source_sha256": hashlib.sha256((ROOT / "test_router.py").read_bytes()).hexdigest(),
        "ddl_sha256": hashlib.sha256(ddl.encode()).hexdigest(),
        "notice": "Actually materialized synthetic projections; no live Scout access. Times are warm-cache single-run measurements, not production latency guarantees.",
        "results": results,
    }, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(report + "\n")
    print(report)


if __name__ == "__main__":
    main()
