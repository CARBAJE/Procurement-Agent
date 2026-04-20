#!/usr/bin/env python3
"""
Database setup automation for Procurement Agent Beckn Protocol.

Reads and executes all SQL scripts from ./sql/ in lexicographic order,
creating the complete PostgreSQL schema end-to-end.

Usage:
    python setup_database.py [--create-db] [--drop-all]

Environment variables (override defaults):
    DB_HOST      host     (default: localhost)
    DB_PORT      port     (default: 5432)
    DB_NAME      dbname   (default: procurement_agent)
    DB_USER      user     (default: postgres)
    DB_PASSWORD  password (default: "")

Examples:
    # First-time setup (create DB + full schema)
    DB_PASSWORD=secret python setup_database.py --create-db

    # Rebuild from scratch (drop everything then recreate)
    DB_PASSWORD=secret python setup_database.py --drop-all

    # Apply scripts to an existing database
    DB_PASSWORD=secret python setup_database.py
"""

import argparse
import os
import sys
from pathlib import Path

try:
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
except ImportError:
    print("ERROR: psycopg2 not installed.\n  Run: pip install psycopg2-binary")
    sys.exit(1)


# ──────────────────────────────────────────────────────────────────────────────
# Connection helpers
# ──────────────────────────────────────────────────────────────────────────────

def _params() -> dict:
    return {
        "host":     os.getenv("DB_HOST",     "localhost"),
        "port":     int(os.getenv("DB_PORT", "5432")),
        "dbname":   os.getenv("DB_NAME",     "procurement_agent"),
        "user":     os.getenv("DB_USER",     "postgres"),
        "password": os.getenv("DB_PASSWORD", ""),
    }


def _connect(params: dict) -> "psycopg2.connection":
    try:
        return psycopg2.connect(**params)
    except psycopg2.OperationalError as exc:
        print(f"  ERROR — cannot connect: {exc}")
        raise


# ──────────────────────────────────────────────────────────────────────────────
# Step 1: create database
# ──────────────────────────────────────────────────────────────────────────────

def create_database(params: dict) -> None:
    db_name = params["dbname"]
    admin = {**params, "dbname": "postgres"}
    conn = _connect(admin)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
        if cur.fetchone():
            print(f"  Database '{db_name}' already exists — skipping creation.")
        else:
            cur.execute(f'CREATE DATABASE "{db_name}"')
            print(f"  Created database '{db_name}'.")
        cur.close()
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# Step 2 (optional): drop all objects
# ──────────────────────────────────────────────────────────────────────────────

_DROP_ALL_SQL = """
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT tablename FROM pg_tables WHERE schemaname = 'public'
    LOOP
        EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
    END LOOP;

    FOR r IN
        SELECT t.typname
        FROM pg_type t
        JOIN pg_namespace n ON t.typnamespace = n.oid
        WHERE n.nspname = 'public' AND t.typtype = 'e'
    LOOP
        EXECUTE 'DROP TYPE IF EXISTS ' || quote_ident(r.typname) || ' CASCADE';
    END LOOP;
END $$;
"""


def drop_all_objects(conn) -> None:
    print("  Dropping all public tables and ENUM types (CASCADE)...")
    cur = conn.cursor()
    cur.execute(_DROP_ALL_SQL)
    conn.commit()
    cur.close()
    print("  Done.")


# ──────────────────────────────────────────────────────────────────────────────
# Step 3: execute SQL files
# ──────────────────────────────────────────────────────────────────────────────

def execute_sql_file(conn, filepath: Path) -> None:
    sql = filepath.read_text(encoding="utf-8")
    cur = conn.cursor()
    try:
        cur.execute(sql)
        conn.commit()
        print(f"  [OK]   {filepath.name}")
    except Exception as exc:
        conn.rollback()
        print(f"  [FAIL] {filepath.name}")
        print(f"         {exc}")
        raise
    finally:
        cur.close()


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Setup Procurement Agent PostgreSQL database end-to-end.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--create-db",
        action="store_true",
        help="Create the target database if it does not already exist.",
    )
    parser.add_argument(
        "--drop-all",
        action="store_true",
        help="Drop all tables and ENUM types before recreating (destructive — use with care).",
    )
    args = parser.parse_args()

    params = _params()
    db_name = params["dbname"]

    print()
    print("═══════════════════════════════════════════════════════")
    print("  Procurement Agent — PostgreSQL Database Setup")
    print("═══════════════════════════════════════════════════════")
    print(f"  Target : {params['user']}@{params['host']}:{params['port']}/{db_name}")
    print()

    # ── Step 1: Create DB ────────────────────────────────────────────────────
    if args.create_db:
        print("Step 1 — Create database")
        create_database(params)
    else:
        print("Step 1 — Skipped (pass --create-db to create the database first)")

    # ── Connect ──────────────────────────────────────────────────────────────
    print("\nConnecting to database...")
    try:
        conn = _connect(params)
    except psycopg2.OperationalError:
        sys.exit(1)
    print(f"  Connected to '{db_name}'.")

    try:
        # ── Step 2 (opt): Drop ───────────────────────────────────────────────
        if args.drop_all:
            print("\nStep 2 — Drop all objects (--drop-all requested)")
            drop_all_objects(conn)

        # ── Step 3: Execute SQL scripts ──────────────────────────────────────
        sql_dir = Path(__file__).parent / "sql"
        sql_files = sorted(sql_dir.glob("*.sql"))

        if not sql_files:
            print(f"\nERROR: No .sql files found in {sql_dir}")
            sys.exit(1)

        print(f"\nStep 3 — Executing {len(sql_files)} SQL scripts")
        for sql_file in sql_files:
            execute_sql_file(conn, sql_file)

        print()
        print("═══════════════════════════════════════════════════════")
        print(f"  Setup complete — {len(sql_files)} scripts executed successfully.")
        print("═══════════════════════════════════════════════════════")
        print()

    except Exception:
        print()
        print("═══════════════════════════════════════════════════════")
        print("  Setup FAILED — see error above.")
        print("═══════════════════════════════════════════════════════")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
