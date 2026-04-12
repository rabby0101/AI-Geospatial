# Query

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Query subsystem handles **9 routes** and touches: auth, db, cache.

## Routes

- `POST` `/query-stats` → in: NLQuery, out: QueryResponse [auth, db, cache]
  `app/routes/query.py`
- `GET` `/datasets` → out: QueryResponse [auth, db, cache]
  `app/routes/query.py`
- `POST` `/execute-sql` → in: NLQuery, out: QueryResponse [auth, db, cache]
  `app/routes/query.py`
- `GET` `/load-table/{table_name}` params(table_name) → out: QueryResponse [auth, db, cache]
  `app/routes/query.py`
- `GET` `/districts-geojson` → out: QueryResponse [auth, db, cache]
  `app/routes/query.py`
- `POST` `/cache/clear` → in: NLQuery, out: QueryResponse [auth, db, cache]
  `app/routes/query.py`
- `POST` `/create-temp-layer` → in: NLQuery, out: QueryResponse [auth, db, cache]
  `app/routes/query.py`
- `POST` `/drop-temp-layer` → in: NLQuery, out: QueryResponse [auth, db, cache]
  `app/routes/query.py`
- `POST` `/street-lights/coverage` → in: NLQuery, out: QueryResponse [auth, db, cache]
  `app/routes/query.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `app/routes/query.py`

---
_Back to [overview.md](./overview.md)_