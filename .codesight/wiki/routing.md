# Routing

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Routing subsystem handles **3 routes** and touches: auth.

## Routes

- `POST` `/connect-features` → in: Dict [auth]
  `app/routes/routing.py`
- `POST` `/nearest-vertex` → in: Dict [auth]
  `app/routes/routing.py`
- `POST` `/optimal-tour` → in: Dict [auth]
  `app/routes/routing.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `app/routes/routing.py`

---
_Back to [overview.md](./overview.md)_