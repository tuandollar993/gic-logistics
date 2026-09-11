"""
Database backup automation script supporting PostgreSQL and SQLite.
Includes connectivity checks, safe dumps, and file rotation.
"""
import os
import sys
import shutil
import sqlite3
import argparse
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / '.env')
except ImportError:
    pass


def parse_database_url(url: str):
    if not url:
        return None
    if url.startswith("sqlite:///"):
        path = url.replace("sqlite:///", "")
        if not os.path.isabs(path):
            path = str(PROJECT_ROOT / path)
        return {"dialect": "sqlite", "path": path}
    elif url.startswith("postgresql://") or url.startswith("postgres://"):
        parsed = urlparse(url)
        return {
            "dialect": "postgresql",
            "host": parsed.hostname or "localhost",
            "port": str(parsed.port or 5432),
            "user": parsed.username or "postgres",
            "password": parsed.password or "",
            "dbname": parsed.path.lstrip("/") if parsed.path else "postgres",
            "url": url,
        }
    return None


def rotate_backups(dest_dir: Path, prefix: str, max_backups: int):
    """Keep only the most recent max_backups files matching prefix."""
    if max_backups <= 0:
        return
    files = sorted(dest_dir.glob(f"{prefix}_*"), key=lambda f: f.stat().st_mtime)
    while len(files) > max_backups:
        oldest = files.pop(0)
        try:
            oldest.unlink()
            print(f"[Backup] Rotated out old backup: {oldest.name}")
        except OSError as e:
            print(f"[Backup] Warning: Could not remove old backup {oldest.name}: {e}")


def backup_sqlite(db_path: str, dest_dir: Path, max_backups: int) -> Path:
    src = Path(db_path)
    if not src.exists():
        raise FileNotFoundError(f"SQLite database file does not exist: {db_path}")

    # Check connection
    conn = sqlite3.connect(src)
    conn.execute("SELECT 1;").fetchone()
    conn.close()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_file = dest_dir / f"gic_backup_{timestamp}.sqlite3"

    # Use SQLite online backup API for safe hot backup
    src_conn = sqlite3.connect(src)
    dest_conn = sqlite3.connect(dest_file)
    src_conn.backup(dest_conn)
    dest_conn.close()
    src_conn.close()

    rotate_backups(dest_dir, "gic_backup", max_backups)
    return dest_file


def backup_postgresql(info: dict, dest_dir: Path, max_backups: int) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_file = dest_dir / f"gic_pg_backup_{timestamp}.sql"

    # Test connection via psycopg2 / sqlalchemy if available
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(info["url"])
        with engine.connect() as conn:
            conn.execute(text("SELECT 1;"))
    except Exception as e:
        raise ConnectionError(f"PostgreSQL connection check failed: {type(e).__name__}")

    # Check if pg_dump is available on system PATH
    # Allow managed/Windows environments where PATH is sanitized by the
    # runner, while retaining normal PATH discovery for local use.
    pg_dump = os.getenv("PG_DUMP_PATH") or shutil.which("pg_dump")
    if pg_dump:
        env = os.environ.copy()
        if info["password"]:
            env["PGPASSWORD"] = info["password"]
        cmd = [
            pg_dump,
            "-h", info["host"],
            "-p", info["port"],
            "-U", info["user"],
            "-d", info["dbname"],
            "-F", "p",  # plain SQL format
            "-f", str(dest_file)
        ]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"pg_dump failed with code {result.returncode}: {result.stderr}")
    else:
        # Fallback: Python-based data dump using SQLAlchemy metadata & tables
        print("[Backup] pg_dump not found in PATH; performing Python-based schema/data dump...")
        from sqlalchemy import create_engine, MetaData
        engine = create_engine(info["url"])
        meta = MetaData()
        meta.reflect(bind=engine)
        with open(dest_file, "w", encoding="utf-8") as f:
            f.write(f"-- GIC Logistics PostgreSQL Backup {timestamp}\n")
            f.write(f"-- Tables: {', '.join(meta.tables.keys())}\n\n")
            with engine.connect() as conn:
                for table_name, table in meta.tables.items():
                    rows = conn.execute(table.select()).fetchall()
                    f.write(f"-- Table: {table_name} ({len(rows)} rows)\n")
                    for row in rows:
                        f.write(f"-- {dict(row._mapping)}\n")
                    f.write("\n")

    rotate_backups(dest_dir, "gic_pg_backup", max_backups)
    return dest_file


def run_backup(dest_dir_str: str = None, max_backups: int = 7) -> str:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        db_url = f"sqlite:///{PROJECT_ROOT / 'data' / 'gic.db'}"

    info = parse_database_url(db_url)
    if not info:
        raise ValueError("Cannot parse DATABASE_URL configuration")

    dest_dir = Path(dest_dir_str) if dest_dir_str else (PROJECT_ROOT / "backups")
    dest_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Backup] Starting backup for dialect: {info['dialect']}")
    if info["dialect"] == "sqlite":
        out = backup_sqlite(info["path"], dest_dir, max_backups)
    elif info["dialect"] == "postgresql":
        out = backup_postgresql(info, dest_dir, max_backups)
    else:
        raise ValueError(f"Unsupported database dialect: {info['dialect']}")

    print(f"[Backup] Backup created successfully: {out.name} ({out.stat().st_size} bytes)")
    return str(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backup GIC Logistics Database")
    parser.add_argument("--dest-dir", default=None, help="Directory to save backup files")
    parser.add_argument("--max-backups", type=int, default=7, help="Number of backup files to retain")
    args = parser.parse_args()

    try:
        path = run_backup(args.dest_dir, args.max_backups)
        sys.exit(0)
    except Exception as exc:
        print(f"[Backup Error] {exc}", file=sys.stderr)
        sys.exit(1)
