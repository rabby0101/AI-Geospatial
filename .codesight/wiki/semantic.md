# Semantic

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Semantic subsystem handles **7 routes**.

## Routes

- `GET` `/datasets/{dataset_id}` params(dataset_id)
  `app/routes/semantic.py`
- `GET` `/datasets/by-purpose/{purpose}` params(purpose)
  `app/routes/semantic.py`
- `GET` `/ontology`
  `app/routes/semantic.py`
- `POST` `/sparql` → in: SPARQLQueryRequest
  `app/routes/semantic.py`
- `POST` `/validate` → in: SPARQLQueryRequest
  `app/routes/semantic.py`
- `GET` `/statistics`
  `app/routes/semantic.py`
- `POST` `/load-catalog` → in: SPARQLQueryRequest
  `app/routes/semantic.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `app/routes/semantic.py`

---
_Back to [overview.md](./overview.md)_