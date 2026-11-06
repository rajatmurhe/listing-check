"""Keeps the demo state as one JSON document.

Uses Postgres when DATABASE_URL is set (so the run history survives restarts on
Render), otherwise a local SQLite file.
"""
from __future__ import annotations

import json
import os
import sqlite3

DATABASE_URL = os.environ.get("DATABASE_URL", "")


class Store:
    def __init__(self):
        if DATABASE_URL:
            import psycopg  # type: ignore

            self._psycopg = psycopg
            self._connect()
            self.kind = "postgres"
        else:
            path = os.environ.get("SQLITE_PATH", "listingcheck.db")
            self.db = sqlite3.connect(path, check_same_thread=False)
            self.db.execute("create table if not exists kv (k text primary key, v text not null)")
            self.db.commit()
            self.kind = "sqlite"

    def _connect(self):
        self.pg = self._psycopg.connect(DATABASE_URL, autocommit=True)
        with self.pg.cursor() as c:
            c.execute("create table if not exists kv (k text primary key, v text not null)")

    def _pg(self, sql, args, fetch=False):
        for attempt in (1, 2):
            try:
                with self.pg.cursor() as c:
                    c.execute(sql, args)
                    return c.fetchone() if fetch else None
            except self._psycopg.OperationalError:
                if attempt == 2:
                    raise
                self._connect()  # the free database drops idle connections

    def get(self, key: str):
        if self.kind == "postgres":
            row = self._pg("select v from kv where k=%s", (key,), fetch=True)
        else:
            row = self.db.execute("select v from kv where k=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, value) -> None:
        v = json.dumps(value)
        if self.kind == "postgres":
            self._pg("insert into kv (k, v) values (%s, %s) on conflict (k) do update set v = excluded.v", (key, v))
        else:
            self.db.execute("insert into kv (k, v) values (?, ?) on conflict(k) do update set v = excluded.v", (key, v))
            self.db.commit()
