# Walking_distance

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Walking_distance subsystem handles **3 routes** and touches: db.

## Routes

- `POST` `/reachable-roads` → in: Dict [db]
  `app/routes/walking_distance.py`
- `POST` `/find-buildings` → in: Dict [db]
  `app/routes/walking_distance.py`
- `POST` `/coverage` → in: Dict [db]
  `app/routes/walking_distance.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `app/routes/walking_distance.py`

---
_Back to [overview.md](./overview.md)_