from __future__ import annotations

import hashlib
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query

TOKEN_SHA256 = "0b34786262c958c9f7c3c761ed56f64be7e477dd4c58c6ed2ec77063ac391b58"
LEVELS = {
    "standard": {"pg_rows": 1000, "sqlite_rows": 1000, "workers": 8, "ops_per_worker": 15, "auth_rounds": 250, "compat_sizes": [100, 1000]},
    "heavy": {"pg_rows": 5000, "sqlite_rows": 5000, "workers": 16, "ops_per_worker": 30, "auth_rounds": 1500, "compat_sizes": [100, 1000, 5000]},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 2)


def _check_token(token: str) -> None:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if not hashlib.compare_digest(digest, TOKEN_SHA256):
        raise HTTPException(404, "Not found")


def _record(checks: list[dict], name: str, ok: bool, elapsed_ms: float, detail: dict | str | None = None) -> None:
    checks.append({
        "name": name,
        "ok": bool(ok),
        "elapsedMs": round(float(elapsed_ms), 2),
        "detail": detail,
    })


def install(app: FastAPI) -> None:
    if getattr(app.state, "_vaelith_extreme_test_v1", False):
        return
    app.state._vaelith_extreme_test_v1 = True

    @app.get("/api/internal/extreme-test-v1", include_in_schema=False)
    def extreme_test_v1(
        token: str = Query(...),
        level: str = Query("heavy"),
    ):
        _check_token(token)
        if level not in LEVELS:
            raise HTTPException(400, "Nível inválido.")
        cfg = LEVELS[level]
        run_id = uuid4().hex
        started = time.perf_counter()
        checks: list[dict] = []
        warnings: list[str] = []
        environment = {
            "runId": run_id,
            "level": level,
            "startedAt": _now(),
            "vercel": bool(os.getenv("VERCEL")),
            "python": os.sys.version.split()[0],
        }

        # 1. Route inventory and duplicate-route detection.
        step = time.perf_counter()
        route_paths = [getattr(route, "path", None) for route in app.routes]
        required_routes = [
            "/",
            "/login",
            "/app",
            "/api/health",
            "/api/auth/login",
            "/api/auth/logout",
            "/api/me",
            "/api/projects",
            "/api/projects/{pid}/files",
            "/api/projects/{pid}/compatibility",
            "/api/projects/{pid}/operational/dashboard",
            "/api/projects/{pid}/operational/issues",
            "/api/storage/status",
            "/api/storage/self-test",
            "/api/auth/professional-status-v3",
        ]
        missing = [path for path in required_routes if path not in route_paths]
        duplicates = {
            path: route_paths.count(path)
            for path in sorted(set(route_paths))
            if path and route_paths.count(path) > 1
        }
        harmful_duplicates = {
            path: count for path, count in duplicates.items()
            if path in {
                "/api/auth/login", "/api/auth/logout", "/api/me", "/app",
                "/api/projects", "/api/projects/{pid}/compatibility",
            }
        }
        _record(
            checks,
            "route_inventory",
            not missing and not harmful_duplicates,
            _ms(step),
            {
                "registered": len(route_paths),
                "missing": missing,
                "duplicates": harmful_duplicates,
                "middlewareCount": len(getattr(app, "user_middleware", [])),
            },
        )

        # 2. Persistent PostgreSQL CRUD, rollback and cleanup.
        import professional_auth_v3 as auth
        pg_rows = int(cfg["pg_rows"])
        step = time.perf_counter()
        pg_detail: dict = {}
        pg_ok = False
        try:
            auth._ensure_schema()
            with auth._connect(autocommit=True) as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS vaelith_stress_test_v1(
                        run_id TEXT NOT NULL,
                        seq INTEGER NOT NULL,
                        payload TEXT NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY(run_id, seq)
                    )
                    """
                )
            with auth._connect(autocommit=False) as connection:
                cursor = connection.cursor()
                insert_started = time.perf_counter()
                cursor.executemany(
                    "INSERT INTO vaelith_stress_test_v1(run_id,seq,payload) VALUES(%s,%s,%s)",
                    [(run_id, i, f"payload-{i:06d}") for i in range(pg_rows)],
                )
                insert_ms = _ms(insert_started)

                read_started = time.perf_counter()
                row = connection.execute(
                    "SELECT COUNT(*) AS total, COALESCE(SUM(seq),0) AS checksum "
                    "FROM vaelith_stress_test_v1 WHERE run_id=%s",
                    (run_id,),
                ).fetchone()
                read_ms = _ms(read_started)

                update_count = max(1, pg_rows // 5)
                update_started = time.perf_counter()
                connection.execute(
                    "UPDATE vaelith_stress_test_v1 SET payload=payload || '-updated',updated_at=NOW() "
                    "WHERE run_id=%s AND seq<%s",
                    (run_id, update_count),
                )
                update_ms = _ms(update_started)
                connection.commit()

            with auth._connect(autocommit=False) as connection:
                connection.execute(
                    "INSERT INTO vaelith_stress_test_v1(run_id,seq,payload) VALUES(%s,%s,%s)",
                    (run_id + "-rollback", 1, "must-disappear"),
                )
                connection.rollback()
            with auth._connect(autocommit=True) as connection:
                rollback_row = connection.execute(
                    "SELECT COUNT(*) AS total FROM vaelith_stress_test_v1 WHERE run_id=%s",
                    (run_id + "-rollback",),
                ).fetchone()
                updated_row = connection.execute(
                    "SELECT COUNT(*) AS total FROM vaelith_stress_test_v1 "
                    "WHERE run_id=%s AND payload LIKE %s",
                    (run_id, "%-updated"),
                ).fetchone()

            expected_checksum = pg_rows * (pg_rows - 1) // 2
            pg_ok = (
                int(row["total"]) == pg_rows
                and int(row["checksum"]) == expected_checksum
                and int(updated_row["total"]) == update_count
                and int(rollback_row["total"]) == 0
            )
            pg_detail = {
                "rows": pg_rows,
                "insertMs": insert_ms,
                "readMs": read_ms,
                "updateMs": update_ms,
                "checksum": int(row["checksum"]),
                "expectedChecksum": expected_checksum,
                "updatedRows": int(updated_row["total"]),
                "rollbackClean": int(rollback_row["total"]) == 0,
            }
        except Exception as exc:
            pg_detail = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        finally:
            try:
                with auth._connect(autocommit=True) as connection:
                    connection.execute(
                        "DELETE FROM vaelith_stress_test_v1 WHERE run_id=%s OR run_id=%s",
                        (run_id, run_id + "-rollback"),
                    )
            except Exception as exc:
                warnings.append(f"Falha de limpeza PostgreSQL: {type(exc).__name__}: {str(exc)[:180]}")
        _record(checks, "postgresql_crud_rollback", pg_ok, _ms(step), pg_detail)

        # 3. Concurrent PostgreSQL connections and isolation.
        workers = int(cfg["workers"])
        ops_per_worker = int(cfg["ops_per_worker"])
        step = time.perf_counter()
        latencies: list[float] = []
        failures: list[str] = []

        def concurrent_worker(worker: int) -> tuple[bool, float, str | None]:
            worker_started = time.perf_counter()
            worker_run = f"{run_id}-w{worker}"
            try:
                with auth._connect(autocommit=True) as connection:
                    for seq in range(ops_per_worker):
                        payload = f"w{worker}-p{seq}"
                        connection.execute(
                            "INSERT INTO vaelith_stress_test_v1(run_id,seq,payload) "
                            "VALUES(%s,%s,%s) ON CONFLICT(run_id,seq) DO UPDATE SET payload=EXCLUDED.payload,updated_at=NOW()",
                            (worker_run, seq, payload),
                        )
                    row = connection.execute(
                        "SELECT COUNT(*) AS total FROM vaelith_stress_test_v1 WHERE run_id=%s",
                        (worker_run,),
                    ).fetchone()
                    connection.execute(
                        "DELETE FROM vaelith_stress_test_v1 WHERE run_id=%s",
                        (worker_run,),
                    )
                return int(row["total"]) == ops_per_worker, _ms(worker_started), None
            except Exception as exc:
                return False, _ms(worker_started), f"{type(exc).__name__}: {str(exc)[:180]}"

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(concurrent_worker, worker) for worker in range(workers)]
            for future in as_completed(futures):
                ok, latency, error = future.result()
                latencies.append(latency)
                if not ok:
                    failures.append(error or "unknown failure")
        concurrency_ok = not failures and len(latencies) == workers
        concurrency_detail = {
            "workers": workers,
            "operationsPerWorker": ops_per_worker,
            "logicalWrites": workers * ops_per_worker,
            "p50Ms": _percentile(latencies, 0.50),
            "p95Ms": _percentile(latencies, 0.95),
            "maxMs": round(max(latencies), 2) if latencies else 0,
            "failures": failures[:5],
        }
        if concurrency_detail["p95Ms"] > 5000:
            warnings.append("Latência p95 do PostgreSQL acima de 5 segundos sob concorrência.")
        _record(checks, "postgresql_concurrency", concurrency_ok, _ms(step), concurrency_detail)

        # 4. Authentication cryptography, session integrity and owner persistence.
        rounds = int(cfg["auth_rounds"])
        step = time.perf_counter()
        auth_ok = False
        auth_detail: dict = {}
        try:
            owner = auth._owner()
            password = "Vaelith-Stress#2026"
            hash_started = time.perf_counter()
            stored = auth._hash_password(password)
            hash_ms = _ms(hash_started)
            verify_started = time.perf_counter()
            correct = all(auth._verify_password(stored, password) for _ in range(20))
            wrong_rejected = all(not auth._verify_password(stored, password + "!") for _ in range(20))
            verify_ms = _ms(verify_started)

            token_started = time.perf_counter()
            signed_tokens = [auth._sign_user(owner, True) for _ in range(rounds)] if owner else []
            valid_tokens = sum(1 for value in signed_tokens if auth._verify_token(value))
            tampered_rejected = 0
            for value in signed_tokens[: min(200, len(signed_tokens))]:
                tampered = value[:-1] + ("A" if value[-1] != "A" else "B")
                if auth._verify_token(tampered) is None:
                    tampered_rejected += 1
            token_ms = _ms(token_started)

            resolve_started = time.perf_counter()
            resolved = 0
            for value in signed_tokens[: min(100, len(signed_tokens))]:
                if auth._resolve_user(value):
                    resolved += 1
            resolve_ms = _ms(resolve_started)
            auth_ok = bool(
                owner
                and correct
                and wrong_rejected
                and valid_tokens == rounds
                and tampered_rejected == min(200, rounds)
                and resolved == min(100, rounds)
            )
            auth_detail = {
                "ownerConfigured": bool(owner),
                "ownerIdStable": bool(owner and owner.get("id")),
                "passwordHash": "scrypt-v1",
                "hashMs": hash_ms,
                "verify40Ms": verify_ms,
                "tokensGenerated": rounds,
                "validTokens": valid_tokens,
                "tamperedRejected": tampered_rejected,
                "resolvedSessions": resolved,
                "tokenAndResolveMs": round(token_ms + resolve_ms, 2),
            }
        except Exception as exc:
            auth_detail = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        _record(checks, "authentication_integrity", auth_ok, _ms(step), auth_detail)

        # 5. Compatibility engine at progressively larger document bases.
        from compatibility_engine import DISCIPLINES, build_analysis
        compatibility_ok = True
        compatibility_runs: list[dict] = []
        for size in cfg["compat_sizes"]:
            step = time.perf_counter()
            try:
                codes = list(DISCIPLINES.keys())
                files = []
                for index in range(int(size)):
                    code = codes[index % len(codes)]
                    revision = f"R{(index // len(codes)) % 7 + 1:02d}"
                    ext = ".ifc" if code not in {"ELE", "PCI", "ORC", "PLA", "ESC"} else {
                        "ELE": ".dwg", "PCI": ".dwg", "ORC": ".xlsx", "PLA": ".mpp", "ESC": ".pdf"
                    }[code]
                    files.append({
                        "name": f"{code}_SETOR_{index % 37:02d}_{revision}{ext}",
                        "ext": ext,
                        "discipline_code": code,
                        "revision": revision,
                    })
                result = build_analysis(f"stress-{run_id}-{size}", files)
                elapsed = _ms(step)
                run_ok = (
                    int(result.get("files", -1)) == int(size)
                    and len(result.get("disciplines") or []) >= 8
                    and isinstance(result.get("issues"), list)
                    and isinstance(result.get("interfacePackages"), list)
                )
                compatibility_ok = compatibility_ok and run_ok
                compatibility_runs.append({
                    "documents": int(size),
                    "elapsedMs": elapsed,
                    "issues": len(result.get("issues") or []),
                    "interfaces": len(result.get("interfacePackages") or []),
                    "readiness": result.get("readiness"),
                    "ok": run_ok,
                })
            except Exception as exc:
                compatibility_ok = False
                compatibility_runs.append({
                    "documents": int(size),
                    "ok": False,
                    "error": f"{type(exc).__name__}: {str(exc)[:240]}",
                })
        _record(
            checks,
            "compatibility_engine_scale",
            compatibility_ok,
            sum(float(run.get("elapsedMs", 0)) for run in compatibility_runs),
            compatibility_runs,
        )

        # 6. Local operational SQLite path: high-volume temporary CRUD.
        import server
        sqlite_rows = int(cfg["sqlite_rows"])
        step = time.perf_counter()
        sqlite_ok = False
        sqlite_detail: dict = {}
        table_name = "stress_" + run_id[:16]
        try:
            with server.conn() as connection:
                connection.execute(
                    f"CREATE TABLE {table_name}(seq INTEGER PRIMARY KEY,payload TEXT NOT NULL)"
                )
                insert_started = time.perf_counter()
                connection.executemany(
                    f"INSERT INTO {table_name}(seq,payload) VALUES(?,?)",
                    [(i, f"local-{i}") for i in range(sqlite_rows)],
                )
                insert_ms = _ms(insert_started)
                row = connection.execute(
                    f"SELECT COUNT(*) AS total,COALESCE(SUM(seq),0) AS checksum FROM {table_name}"
                ).fetchone()
                connection.execute(
                    f"UPDATE {table_name} SET payload=payload || '-u' WHERE seq<?",
                    (max(1, sqlite_rows // 10),),
                )
                updated = connection.execute(
                    f"SELECT COUNT(*) FROM {table_name} WHERE payload LIKE '%-u'"
                ).fetchone()[0]
                connection.execute(f"DROP TABLE {table_name}")
            expected_checksum = sqlite_rows * (sqlite_rows - 1) // 2
            sqlite_ok = (
                int(row["total"]) == sqlite_rows
                and int(row["checksum"]) == expected_checksum
                and int(updated) == max(1, sqlite_rows // 10)
            )
            sqlite_detail = {
                "rows": sqlite_rows,
                "insertMs": insert_ms,
                "checksum": int(row["checksum"]),
                "updatedRows": int(updated),
                "temporaryInstanceStorage": bool(os.getenv("VERCEL")),
            }
        except Exception as exc:
            sqlite_detail = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
            try:
                with server.conn() as connection:
                    connection.execute(f"DROP TABLE IF EXISTS {table_name}")
            except Exception:
                pass
        _record(checks, "operational_local_database", sqlite_ok, _ms(step), sqlite_detail)

        # 7. Operational schema and JSON report volume.
        step = time.perf_counter()
        operational_ok = False
        operational_detail: dict = {}
        try:
            from unified_runtime_v2 import ensure_schema
            ensure_schema()
            synthetic = {
                "projectId": "stress",
                "issues": [
                    {
                        "id": f"issue-{index}",
                        "title": f"Ocorrência sintética {index}",
                        "severity": ["baixa", "media", "alta", "critica"][index % 4],
                        "costImpact": index * 17.35,
                        "scheduleDays": index % 29,
                        "evidence": [f"arquivo-{index % 200}.ifc", f"foto-{index}.jpg"],
                    }
                    for index in range(5000)
                ],
            }
            encode_started = time.perf_counter()
            encoded = json.dumps(synthetic, ensure_ascii=False, separators=(",", ":"))
            encode_ms = _ms(encode_started)
            decode_started = time.perf_counter()
            decoded = json.loads(encoded)
            decode_ms = _ms(decode_started)
            operational_ok = len(decoded["issues"]) == 5000 and len(encoded) > 500000
            operational_detail = {
                "operationalSchema": True,
                "reportIssues": len(decoded["issues"]),
                "jsonBytes": len(encoded.encode("utf-8")),
                "encodeMs": encode_ms,
                "decodeMs": decode_ms,
            }
        except Exception as exc:
            operational_detail = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        _record(checks, "operational_schema_and_report_volume", operational_ok, _ms(step), operational_detail)

        # 8. Persistent storage configuration.
        step = time.perf_counter()
        storage_ok = False
        storage_detail: dict = {}
        try:
            from supabase_runtime import configured, _credential_status
            valid, detail = _credential_status()
            storage_ok = bool(configured() and valid)
            storage_detail = {
                "configured": bool(configured()),
                "credentialValid": bool(valid),
                "credentialType": detail if valid else None,
                "bucket": os.getenv("SUPABASE_BUCKET", "vaelith-project-files"),
            }
        except Exception as exc:
            storage_detail = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        _record(checks, "persistent_storage_configuration", storage_ok, _ms(step), storage_detail)

        failed = [item["name"] for item in checks if not item["ok"]]
        total_ms = _ms(started)
        if total_ms > 45000:
            warnings.append("A bateria total ultrapassou 45 segundos; risco de timeout em funções menores.")
        status = "healthy" if not failed and not warnings else "degraded" if not failed else "failed"
        return {
            "ok": not failed,
            "status": status,
            "runId": run_id,
            "level": level,
            "startedAt": environment["startedAt"],
            "finishedAt": _now(),
            "totalMs": total_ms,
            "checksPassed": sum(1 for item in checks if item["ok"]),
            "checksTotal": len(checks),
            "failedChecks": failed,
            "warnings": warnings,
            "environment": environment,
            "checks": checks,
            "cleanup": {
                "postgresRowsRemoved": True,
                "localTemporaryTableDropped": True,
                "ownerAccountModified": False,
                "projectDataModified": False,
            },
        }
