from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import config

SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")

pool = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=5, open=False,
                      kwargs={"row_factory": dict_row, "autocommit": False})


def open_pool():
    pool.open(wait=True)
    with pool.connection() as conn:
        conn.execute(SCHEMA_SQL)


def ensure_database():
    """Создаёт базу из DATABASE_URL, если её ещё нет (подключаясь к служебной базе postgres)."""
    info = psycopg.conninfo.conninfo_to_dict(config.DATABASE_URL)
    name = info.get("dbname")
    try:
        psycopg.connect(config.DATABASE_URL).close()
        return
    except psycopg.OperationalError as e:
        if not name or "does not exist" not in str(e):
            raise
    info["dbname"] = "postgres"
    with psycopg.connect(psycopg.conninfo.make_conninfo(**info), autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
