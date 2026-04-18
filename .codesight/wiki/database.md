# Database

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Database subsystem handles **22 routes** and touches: auth, db, cache.

## Routes

- `GET` `/tables` [auth, db, cache, upload]
  `app/routes/database.py`
- `GET` `/tables/{table_name}` params(table_name) [auth, db, cache, upload]
  `app/routes/database.py`
- `POST` `/tables/{table_name}` params(table_name) [auth, db, cache, upload]
  `app/routes/database.py`
- `POST` `/columns` [auth, db, cache, upload]
  `app/routes/database.py`
- `GET` `/schema-for-prompt` [auth, db, cache, upload]
  `app/routes/database.py`
- `POST` `/table-description` [auth, db, cache, upload]
  `app/routes/database.py`
- `GET` `/tables-with-metadata` [auth, db, cache, upload]
  `app/routes/database.py`
- `GET` `/changelog` [auth, db, cache, upload]
  `app/routes/database.py`
- `POST` `/upload` [auth, db, cache, upload]
  `app/routes/database.py`
- `POST` `/upload/check` [auth, db, cache, upload]
  `app/routes/database.py`
- `PUT` `/tables/{table_name}/rename` params(table_name) [auth, db, cache, upload]
  `app/routes/database.py`
- `DELETE` `/tables/{table_name}` params(table_name) [auth, db, cache, upload]
  `app/routes/database.py`
- `GET` `/tables/{table_name}/preview` params(table_name) [auth, db, cache, upload]
  `app/routes/database.py`
- `GET` `/tables/{table_name}/stats` params(table_name) [auth, db, cache, upload]
  `app/routes/database.py`
- `GET` `/schema/status` [auth, db, cache, upload]
  `app/routes/database.py`
- `POST` `/wfs-capabilities` [auth, db, cache, upload]
  `app/routes/database.py`
- `POST` `/wfs-import/check` [auth, db, cache, upload]
  `app/routes/database.py`
- `POST` `/wfs-import` [auth, db, cache, upload]
  `app/routes/database.py`
- `POST` `/overpass/generate-query` [auth, db, cache, upload]
  `app/routes/database.py`
- `POST` `/overpass/query` [auth, db, cache, upload]
  `app/routes/database.py`
- `POST` `/overpass/import/check` [auth, db, cache, upload]
  `app/routes/database.py`
- `POST` `/overpass/import` [auth, db, cache, upload]
  `app/routes/database.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `app/routes/database.py`

---
_Back to [overview.md](./overview.md)_