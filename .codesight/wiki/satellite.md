# Satellite

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Satellite subsystem handles **2 routes** and touches: auth, db.

## Routes

- `POST` `/analyze` → in: List, out: SatelliteUploadResponse [auth, db, upload]
  `app/routes/satellite.py`
- `DELETE` `/session/{session_id}` params(session_id) → out: SatelliteUploadResponse [auth, db, upload]
  `app/routes/satellite.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `app/routes/satellite.py`

---
_Back to [overview.md](./overview.md)_