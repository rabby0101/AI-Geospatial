# Safety

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Safety subsystem handles **11 routes** and touches: db, cache.

## Routes

- `GET` `/mitte/summary` [db, cache]
  `app/routes/safety.py`
- `GET` `/mitte/geojson` [db, cache]
  `app/routes/safety.py`
- `GET` `/mitte/lighting` [db, cache]
  `app/routes/safety.py`
- `GET` `/mitte/activity-nodes` [db, cache]
  `app/routes/safety.py`
- `GET` `/mitte/emergency-services` [db, cache]
  `app/routes/safety.py`
- `GET` `/mitte/buildings` [db, cache]
  `app/routes/safety.py`
- `POST` `/analysis/export` [db, cache]
  `app/routes/safety.py`
- `GET` `/mitte/crime-summary` [db, cache]
  `app/routes/safety.py`
- `GET` `/mitte/accidents` [db, cache]
  `app/routes/safety.py`
- `GET` `/mitte/hotspots` [db, cache]
  `app/routes/safety.py`
- `GET` `/mitte/risk-heatmap` [db, cache]
  `app/routes/safety.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `app/routes/safety.py`

---
_Back to [overview.md](./overview.md)_