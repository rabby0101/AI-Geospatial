# Geocoding

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Geocoding subsystem handles **4 routes** and touches: db.

## Routes

- `GET` `/search` → in: st, out: GeocodeSearchResponse [db]
  `app/routes/geocoding.py`
- `GET` `/autocomplete` → in: st, out: GeocodeSearchResponse [db]
  `app/routes/geocoding.py`
- `GET` `/reverse` → in: st, out: GeocodeSearchResponse [db]
  `app/routes/geocoding.py`
- `GET` `/feature` → in: st, out: GeocodeSearchResponse [db]
  `app/routes/geocoding.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `app/routes/geocoding.py`

---
_Back to [overview.md](./overview.md)_