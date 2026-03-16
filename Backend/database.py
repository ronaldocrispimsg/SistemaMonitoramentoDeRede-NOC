from threading import Lock
from pathlib import Path
import sqlite3
import time
import os
import shutil
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./noclite.db")
logger = logging.getLogger("noc_lite.database")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30}
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()
_SCHEMA_READY = False
_SCHEMA_LOCK = Lock()
_HEALTH_READY = False
_HEALTH_LOCK = Lock()
_SANITIZE_READY = False
_SANITIZE_LOCK = Lock()


def _sqlite_db_path() -> Path | None:
    if not DATABASE_URL.startswith("sqlite:///"):
        return None
    raw = DATABASE_URL.replace("sqlite:///", "", 1)
    return Path(raw).resolve()


def _run_sqlite_check(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path), timeout=10)
    try:
        row = conn.execute("PRAGMA quick_check;").fetchone()
        return str(row[0] if row else "unknown")
    finally:
        conn.close()


def ensure_runtime_health() -> None:
    """
    Tenta recuperar automaticamente corrupção comum de WAL/SHM.
    Executa apenas uma vez por processo.
    """
    global _HEALTH_READY
    if _HEALTH_READY:
        return

    with _HEALTH_LOCK:
        if _HEALTH_READY:
            return

        db_path = _sqlite_db_path()
        if db_path is None or not db_path.exists():
            _HEALTH_READY = True
            return

        result = _run_sqlite_check(db_path)
        if result == "ok":
            _HEALTH_READY = True
            return

        wal = db_path.with_name(f"{db_path.name}-wal")
        shm = db_path.with_name(f"{db_path.name}-shm")
        if wal.exists() or shm.exists():
            stamp = int(time.time())
            if wal.exists():
                backup_wal = wal.with_name(f"{wal.name}.corrupt.{stamp}.bak")
                shutil.move(str(wal), str(backup_wal))
                logger.warning("WAL movido para backup: %s", backup_wal)
            if shm.exists():
                backup_shm = shm.with_name(f"{shm.name}.corrupt.{stamp}.bak")
                shutil.move(str(shm), str(backup_shm))
                logger.warning("SHM movido para backup: %s", backup_shm)

            result = _run_sqlite_check(db_path)
            if result == "ok":
                logger.warning("Banco SQLite recuperado após limpeza de WAL/SHM")
                _HEALTH_READY = True
                return

        raise RuntimeError(
            f"Banco SQLite inconsistente (quick_check={result}). "
            "Restaure a partir de backup do noclite.db."
        )


def ensure_runtime_schema() -> None:
    """
    Ajustes de schema leves para bancos SQLite já existentes, sem migração formal.
    Executa uma vez por processo.
    """
    global _SCHEMA_READY
    if _SCHEMA_READY:
        sanitize_legacy_datetime_values()
        return

    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            sanitize_legacy_datetime_values()
            return

        ensure_runtime_health()

        retries = 8
        for attempt in range(retries):
            try:
                with engine.begin() as conn:
                    cols = conn.execute(text("PRAGMA table_info(hosts)")).fetchall()
                    if not cols:
                        _SCHEMA_READY = True
                        break

                    col_names = {row[1] for row in cols}
                    if "deleted_at" not in col_names:
                        conn.execute(text("ALTER TABLE hosts ADD COLUMN deleted_at DATETIME"))
                    if "baseline_pending" not in col_names:
                        conn.execute(
                            text(
                                "ALTER TABLE hosts ADD COLUMN baseline_pending BOOLEAN NOT NULL DEFAULT 1"
                            )
                        )
                    if "tcp_ports" not in col_names:
                        conn.execute(text("ALTER TABLE hosts ADD COLUMN tcp_ports TEXT"))
                        conn.execute(
                            text(
                                """
                                UPDATE hosts
                                SET tcp_ports = '[' || CAST(port AS TEXT) || ']'
                                WHERE port IS NOT NULL
                                """
                            )
                        )
                    if "snmp_enabled" not in col_names:
                        conn.execute(
                            text(
                                "ALTER TABLE hosts ADD COLUMN snmp_enabled BOOLEAN NOT NULL DEFAULT 0"
                            )
                        )
                        conn.execute(
                            text(
                                """
                                UPDATE hosts
                                SET snmp_enabled = 1
                                WHERE lower(trim(coalesce(snmp_community, ''))) = 'noc-lite'
                                """
                            )
                        )
                    if "http_enabled" not in col_names:
                        conn.execute(
                            text(
                                "ALTER TABLE hosts ADD COLUMN http_enabled BOOLEAN NOT NULL DEFAULT 1"
                            )
                        )
                        conn.execute(
                            text(
                                """
                                UPDATE hosts
                                SET http_enabled = 1
                                WHERE trim(coalesce(http_url, '')) <> ''
                                """
                            )
                        )
                    if "last_http_protocol" not in col_names:
                        conn.execute(text("ALTER TABLE hosts ADD COLUMN last_http_protocol TEXT"))
                    if "http_latency" not in col_names:
                        conn.execute(text("ALTER TABLE hosts ADD COLUMN http_latency FLOAT"))
                    if "https_latency" not in col_names:
                        conn.execute(text("ALTER TABLE hosts ADD COLUMN https_latency FLOAT"))
                    if "web_tcp_port" not in col_names:
                        conn.execute(text("ALTER TABLE hosts ADD COLUMN web_tcp_port INTEGER"))
                    if "web_tcp_port_latency" not in col_names:
                        conn.execute(text("ALTER TABLE hosts ADD COLUMN web_tcp_port_latency FLOAT"))
                    if "tcp_http_port_latency" not in col_names:
                        conn.execute(text("ALTER TABLE hosts ADD COLUMN tcp_http_port_latency FLOAT"))
                    if "tcp_https_port_latency" not in col_names:
                        conn.execute(text("ALTER TABLE hosts ADD COLUMN tcp_https_port_latency FLOAT"))
                    if "tcp_http_port_ok" not in col_names:
                        conn.execute(text("ALTER TABLE hosts ADD COLUMN tcp_http_port_ok BOOLEAN"))
                    if "tcp_https_port_ok" not in col_names:
                        conn.execute(text("ALTER TABLE hosts ADD COLUMN tcp_https_port_ok BOOLEAN"))

                    check_cols = conn.execute(text("PRAGMA table_info(checks)")).fetchall()
                    if check_cols:
                        check_col_names = {row[1] for row in check_cols}
                        if "tcp_port" not in check_col_names:
                            conn.execute(text("ALTER TABLE checks ADD COLUMN tcp_port INTEGER"))
                _SCHEMA_READY = True
                break
            except OperationalError as exc:
                message = str(exc).lower()
                if "duplicate column name" in message:
                    _SCHEMA_READY = True
                    break
                if "database is locked" in message and attempt < retries - 1:
                    time.sleep(0.35)
                    continue
                raise

        _SCHEMA_READY = True

    sanitize_legacy_datetime_values()


def sanitize_legacy_datetime_values() -> None:
    """
    Limpa valores inválidos em colunas DateTime (ex.: IP/texto legado em campo de data).
    Isso evita ValueError no carregamento ORM.
    Executa apenas uma vez por processo.
    """
    global _SANITIZE_READY
    if _SANITIZE_READY:
        return

    with _SANITIZE_LOCK:
        if _SANITIZE_READY:
            return

        datetime_columns = {
            "hosts": [
                "active_time",
                "deleted_at",
                "last_check",
                "last_ttl_alert",
                "last_preventive_alert",
                "last_net_check",
                "last_snmp_check",
            ],
            "alerts": ["timestamp"],
            "incidents": ["started_time", "ended_time"],
            "checks": ["timestamp"],
            "snmp_metrics": ["timestamp"],
            "dns_cache": ["resolved_time", "expires_time"],
            "users": ["locked_until"],
        }

        retries = 8
        for attempt in range(retries):
            try:
                with engine.begin() as conn:
                    total_fixed = 0
                    for table, columns in datetime_columns.items():
                        table_cols = conn.execute(
                            text(f"PRAGMA table_info({table})")
                        ).fetchall()
                        if not table_cols:
                            continue
                        table_col_names = {row[1] for row in table_cols}
                        for col in columns:
                            if col not in table_col_names:
                                continue

                            fixed = conn.execute(
                                text(
                                    f"""
                                    UPDATE {table}
                                    SET {col} = NULL
                                    WHERE {col} IS NOT NULL
                                      AND julianday({col}) IS NULL
                                    """
                                )
                            ).rowcount or 0
                            if fixed:
                                total_fixed += fixed
                                logger.warning(
                                    "Saneamento DateTime: %s.%s teve %s registro(s) corrigido(s)",
                                    table,
                                    col,
                                    fixed,
                                )

                    if total_fixed:
                        logger.warning(
                            "Saneamento DateTime concluído: %s registro(s) inválido(s) ajustado(s) para NULL",
                            total_fixed,
                        )
                _SANITIZE_READY = True
                return
            except OperationalError as exc:
                message = str(exc).lower()
                if "database is locked" in message and attempt < retries - 1:
                    time.sleep(0.35)
                    continue
                raise

        _SANITIZE_READY = True

def get_db():
    ensure_runtime_schema()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
