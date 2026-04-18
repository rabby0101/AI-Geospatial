# Raster

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Raster subsystem handles **8 routes**.

## Routes

- `POST` `/ndvi/change-detection` → in: NDVIChangeRequest
  `app/routes/raster.py`
- `POST` `/ndvi/zonal-stats` → in: NDVIChangeRequest
  `app/routes/raster.py`
- `GET` `/ndvi/timeseries/{region}` params(region)
  `app/routes/raster.py`
- `POST` `/clip` → in: NDVIChangeRequest
  `app/routes/raster.py`
- `POST` `/vectorize` → in: NDVIChangeRequest
  `app/routes/raster.py`
- `GET` `/catalog`
  `app/routes/raster.py`
- `GET` `/info/{dataset_id}` params(dataset_id)
  `app/routes/raster.py`
- `POST` `/analyze/urban-vegetation-loss` → in: NDVIChangeRequest
  `app/routes/raster.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `app/routes/raster.py`

---
_Back to [overview.md](./overview.md)_