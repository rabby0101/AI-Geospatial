# Structured Database Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured database-control actions to Database Inspector without exposing arbitrary SQL.

**Architecture:** Keep all database mutations behind typed FastAPI endpoints that validate schema, table, column, and row identifiers before generating SQL. The UI extends the existing single-file inspector with table-local control sections for rows, schema, indexes, and table operations, reusing the current `/api/database` prefix and `vector` schema convention.

**Tech Stack:** FastAPI, SQLAlchemy Core, PostgreSQL/PostGIS, plain HTML/CSS/JavaScript, pytest, FastAPI TestClient.

---

## File Structure

- Modify `app/routes/database.py`
  - Add Pydantic request models for row, column, table, and index operations.
  - Add helper functions for identifier validation, table inspection, primary-key detection, type allowlists, value coercion, and row predicates.
  - Add structured endpoints for rows, columns, indexes, clone/truncate/export, and empty-table creation.
- Modify `frontend/database-inspector.html`
  - Add table-detail sub-tabs: `Data`, `Columns`, `Indexes`, `Operations`.
  - Add row editor modal, column editor modal, index form, and table operation controls.
  - Add client-side helpers that call only structured endpoints.
- Create `tests/test_database_control_api.py`
  - Unit-style API tests using monkeypatched SQLAlchemy engine/inspector where possible.
  - Validation tests for unsafe identifiers and unsupported column types.
  - Endpoint tests for request/response contracts.

## API Contract

Structured endpoints to add:

- `GET /api/database/tables/{table_name}/rows?page=1&per_page=50&sort_col=&sort_dir=asc&filter_col=&filter_val=`
- `POST /api/database/tables/{table_name}/rows`
- `PUT /api/database/tables/{table_name}/rows`
- `DELETE /api/database/tables/{table_name}/rows`
- `POST /api/database/tables/{table_name}/rows/duplicate`
- `POST /api/database/tables/{table_name}/columns`
- `PUT /api/database/tables/{table_name}/columns/{column_name}/rename`
- `PUT /api/database/tables/{table_name}/columns/{column_name}/nullable`
- `PUT /api/database/tables/{table_name}/columns/{column_name}/default`
- `PUT /api/database/tables/{table_name}/columns/{column_name}/type`
- `DELETE /api/database/tables/{table_name}/columns/{column_name}`
- `GET /api/database/tables/{table_name}/indexes`
- `POST /api/database/tables/{table_name}/indexes`
- `DELETE /api/database/tables/{table_name}/indexes/{index_name}`
- `POST /api/database/tables/{table_name}/clone`
- `POST /api/database/tables/{table_name}/truncate`
- `GET /api/database/tables/{table_name}/export`
- `POST /api/database/tables/create`

Row identity rule:

- Prefer primary key columns from SQLAlchemy inspector.
- If no primary key exists, expose PostgreSQL `ctid` as `_row_ref` for existing-row update/delete/duplicate.
- Insert does not need `_row_ref`.

Allowed column types for schema edits:

```python
ALLOWED_COLUMN_TYPES = {
    "text": "TEXT",
    "varchar": "VARCHAR",
    "integer": "INTEGER",
    "bigint": "BIGINT",
    "double": "DOUBLE PRECISION",
    "numeric": "NUMERIC",
    "boolean": "BOOLEAN",
    "date": "DATE",
    "timestamp": "TIMESTAMP",
    "geometry": "geometry(Geometry, 4326)",
}
```

---

### Task 1: Backend Validation and Inspection Helpers

**Files:**
- Modify: `app/routes/database.py`
- Test: `tests/test_database_control_api.py`

- [ ] **Step 1: Write validation tests**

Add `tests/test_database_control_api.py`:

```python
import pytest
from fastapi import HTTPException

from app.routes import database


def test_validate_identifier_accepts_simple_names():
    assert database._validate_identifier("osm_hospitals", "table") == "osm_hospitals"
    assert database._validate_identifier("name_2", "column") == "name_2"


@pytest.mark.parametrize("value", ["", "a-b", "AName", "x;drop", "table.name", " name"])
def test_validate_identifier_rejects_unsafe_names(value):
    with pytest.raises(HTTPException) as exc:
        database._validate_identifier(value, "table")
    assert exc.value.status_code == 400


def test_normalize_column_type_accepts_allowlisted_types():
    assert database._normalize_column_type("text") == "TEXT"
    assert database._normalize_column_type("INTEGER") == "INTEGER"
    assert database._normalize_column_type("geometry") == "geometry(Geometry, 4326)"


def test_normalize_column_type_rejects_unlisted_types():
    with pytest.raises(HTTPException) as exc:
        database._normalize_column_type("serial primary key")
    assert exc.value.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_database_control_api.py -q
```

Expected: fail because `_validate_identifier` and `_normalize_column_type` do not exist.

- [ ] **Step 3: Add helper implementation**

Add near the existing helper section in `app/routes/database.py`:

```python
import re
import csv
import io

IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")

ALLOWED_COLUMN_TYPES = {
    "text": "TEXT",
    "varchar": "VARCHAR",
    "integer": "INTEGER",
    "bigint": "BIGINT",
    "double": "DOUBLE PRECISION",
    "numeric": "NUMERIC",
    "boolean": "BOOLEAN",
    "date": "DATE",
    "timestamp": "TIMESTAMP",
    "geometry": "geometry(Geometry, 4326)",
}


def _validate_identifier(value: str, label: str = "identifier") -> str:
    if not value or not IDENTIFIER_RE.fullmatch(value):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {label}. Use lowercase letters, numbers and underscores, starting with a letter.",
        )
    return value


def _quote_ident(value: str) -> str:
    return f'"{_validate_identifier(value)}"'


def _normalize_column_type(raw_type: str) -> str:
    key = (raw_type or "").strip().lower()
    if key not in ALLOWED_COLUMN_TYPES:
        allowed = ", ".join(sorted(ALLOWED_COLUMN_TYPES))
        raise HTTPException(status_code=400, detail=f"Unsupported column type. Allowed: {allowed}")
    return ALLOWED_COLUMN_TYPES[key]


def _get_vector_columns(inspector, table_name: str) -> List[Dict]:
    if not inspector.has_table(table_name, schema="vector"):
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")
    return inspector.get_columns(table_name, schema="vector")


def _get_column_names(inspector, table_name: str) -> List[str]:
    return [c["name"] for c in _get_vector_columns(inspector, table_name)]


def _get_primary_key_columns(inspector, table_name: str) -> List[str]:
    pk = inspector.get_pk_constraint(table_name, schema="vector") or {}
    return pk.get("constrained_columns") or []
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_database_control_api.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add app/routes/database.py tests/test_database_control_api.py
git commit -m "feat: add database control validation helpers"
```

---

### Task 2: Row Browse, Insert, Update, Delete, Duplicate

**Files:**
- Modify: `app/routes/database.py`
- Modify: `tests/test_database_control_api.py`

- [ ] **Step 1: Write row endpoint contract tests**

Append:

```python
from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


def test_row_insert_rejects_unknown_column(monkeypatch):
    class FakeInspector:
        def has_table(self, table_name, schema=None):
            return table_name == "sample_table" and schema == "vector"

        def get_columns(self, table_name, schema=None):
            return [{"name": "id", "type": "INTEGER"}, {"name": "name", "type": "TEXT"}]

        def get_pk_constraint(self, table_name, schema=None):
            return {"constrained_columns": ["id"]}

    monkeypatch.setattr(database, "inspect", lambda engine: FakeInspector())
    monkeypatch.setattr(database, "get_db_engine", lambda: object())

    response = client.post("/api/database/tables/sample_table/rows", json={"values": {"bad": "x"}})
    assert response.status_code == 400
    assert "Unknown column" in response.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_database_control_api.py::test_row_insert_rejects_unknown_column -q
```

Expected: fail with 404 because the endpoint does not exist.

- [ ] **Step 3: Add row request models**

Add with the other Pydantic models:

```python
class RowCreateRequest(BaseModel):
    values: Dict[str, object]


class RowMutationRequest(BaseModel):
    row_ref: Dict[str, object]
    values: Dict[str, object]


class RowRefRequest(BaseModel):
    row_ref: Dict[str, object]
```

- [ ] **Step 4: Add row predicate/value helpers**

Add near validation helpers:

```python
def _validate_values_against_columns(values: Dict[str, object], column_names: List[str]) -> Dict[str, object]:
    unknown = sorted(set(values.keys()) - set(column_names))
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown column(s): {', '.join(unknown)}")
    return values


def _build_row_predicate(row_ref: Dict[str, object], pk_columns: List[str]) -> tuple[str, Dict[str, object]]:
    if pk_columns:
        missing = [c for c in pk_columns if c not in row_ref]
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing primary key value(s): {', '.join(missing)}")
        clauses = [f'"{c}" = :pk_{c}' for c in pk_columns]
        return " AND ".join(clauses), {f"pk_{c}": row_ref[c] for c in pk_columns}

    ctid = row_ref.get("_row_ref")
    if not ctid:
        raise HTTPException(status_code=400, detail="Missing _row_ref for table without primary key")
    return "ctid = :row_ctid", {"row_ctid": ctid}
```

- [ ] **Step 5: Add row endpoints**

Add after the existing `preview_table` endpoint:

```python
@router.get("/tables/{table_name}/rows")
async def browse_rows(
    table_name: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    sort_col: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    filter_col: Optional[str] = None,
    filter_val: Optional[str] = None,
):
    table_name = _validate_identifier(table_name, "table name")
    engine = get_db_engine()
    inspector = inspect(engine)
    cols = _get_vector_columns(inspector, table_name)
    col_names = [c["name"] for c in cols]
    pk_columns = _get_primary_key_columns(inspector, table_name)

    if sort_col and sort_col not in col_names:
        raise HTTPException(status_code=400, detail=f"Unknown sort column: {sort_col}")
    if filter_col and filter_col not in col_names:
        raise HTTPException(status_code=400, detail=f"Unknown filter column: {filter_col}")

    offset = (page - 1) * per_page
    params: Dict[str, object] = {"limit": per_page, "offset": offset}

    select_parts = ['ctid::text AS "_row_ref"'] if not pk_columns else []
    for col in cols:
        if "geometry" in str(col["type"]).lower():
            select_parts.append(f'ST_AsText("{col["name"]}") AS "{col["name"]}"')
        else:
            select_parts.append(f'"{col["name"]}"')

    where_sql = ""
    if filter_col and filter_val is not None:
        where_sql = f'WHERE "{filter_col}"::text ILIKE :filter_val'
        params["filter_val"] = f"%{filter_val}%"

    order_sql = f'ORDER BY "{sort_col}" {sort_dir.upper()}' if sort_col else ""

    with engine.connect() as conn:
        total = conn.execute(text(f'SELECT COUNT(*) FROM vector."{table_name}" {where_sql}'), params).scalar() or 0
        result = conn.execute(
            text(f'SELECT {", ".join(select_parts)} FROM vector."{table_name}" {where_sql} {order_sql} LIMIT :limit OFFSET :offset'),
            params,
        )
        columns = list(result.keys())
        rows = [dict(zip(columns, row)) for row in result.fetchall()]

    return {
        "success": True,
        "table_name": table_name,
        "columns": columns,
        "rows": rows,
        "pk_columns": pk_columns,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": (total + per_page - 1) // per_page,
    }


@router.post("/tables/{table_name}/rows")
async def insert_row(table_name: str, body: RowCreateRequest):
    table_name = _validate_identifier(table_name, "table name")
    engine = get_db_engine()
    inspector = inspect(engine)
    col_names = _get_column_names(inspector, table_name)
    values = _validate_values_against_columns(body.values, col_names)
    if not values:
        raise HTTPException(status_code=400, detail="At least one column value is required")

    insert_cols = list(values.keys())
    col_sql = ", ".join(f'"{c}"' for c in insert_cols)
    val_sql = ", ".join(f":v_{c}" for c in insert_cols)
    params = {f"v_{c}": values[c] for c in insert_cols}

    with engine.connect() as conn:
        conn.execute(text(f'INSERT INTO vector."{table_name}" ({col_sql}) VALUES ({val_sql})'), params)
        conn.commit()

    _log_change(engine, table_name, "row_insert", {"columns": insert_cols})
    return {"success": True, "message": "Row inserted"}


@router.put("/tables/{table_name}/rows")
async def update_row(table_name: str, body: RowMutationRequest):
    table_name = _validate_identifier(table_name, "table name")
    engine = get_db_engine()
    inspector = inspect(engine)
    col_names = _get_column_names(inspector, table_name)
    pk_columns = _get_primary_key_columns(inspector, table_name)
    values = _validate_values_against_columns(body.values, col_names)
    if not values:
        raise HTTPException(status_code=400, detail="At least one column value is required")

    predicate_sql, predicate_params = _build_row_predicate(body.row_ref, pk_columns)
    set_cols = list(values.keys())
    set_sql = ", ".join(f'"{c}" = :v_{c}' for c in set_cols)
    params = {f"v_{c}": values[c] for c in set_cols}
    params.update(predicate_params)

    with engine.connect() as conn:
        result = conn.execute(text(f'UPDATE vector."{table_name}" SET {set_sql} WHERE {predicate_sql}'), params)
        conn.commit()

    _log_change(engine, table_name, "row_update", {"columns": set_cols})
    return {"success": True, "updated": result.rowcount}


@router.delete("/tables/{table_name}/rows")
async def delete_row(table_name: str, body: RowRefRequest):
    table_name = _validate_identifier(table_name, "table name")
    engine = get_db_engine()
    inspector = inspect(engine)
    _get_vector_columns(inspector, table_name)
    pk_columns = _get_primary_key_columns(inspector, table_name)
    predicate_sql, params = _build_row_predicate(body.row_ref, pk_columns)

    with engine.connect() as conn:
        result = conn.execute(text(f'DELETE FROM vector."{table_name}" WHERE {predicate_sql}'), params)
        conn.commit()

    _log_change(engine, table_name, "row_delete", {"row_ref": body.row_ref})
    return {"success": True, "deleted": result.rowcount}


@router.post("/tables/{table_name}/rows/duplicate")
async def duplicate_row(table_name: str, body: RowRefRequest):
    table_name = _validate_identifier(table_name, "table name")
    engine = get_db_engine()
    inspector = inspect(engine)
    cols = _get_vector_columns(inspector, table_name)
    pk_columns = _get_primary_key_columns(inspector, table_name)
    predicate_sql, params = _build_row_predicate(body.row_ref, pk_columns)
    copy_cols = [c["name"] for c in cols if c["name"] not in pk_columns]
    if not copy_cols:
        raise HTTPException(status_code=400, detail="No non-primary-key columns available to duplicate")
    col_sql = ", ".join(f'"{c}"' for c in copy_cols)

    with engine.connect() as conn:
        result = conn.execute(
            text(f'INSERT INTO vector."{table_name}" ({col_sql}) SELECT {col_sql} FROM vector."{table_name}" WHERE {predicate_sql}'),
            params,
        )
        conn.commit()

    _log_change(engine, table_name, "row_duplicate", {"row_ref": body.row_ref})
    return {"success": True, "duplicated": result.rowcount}
```

- [ ] **Step 6: Run row tests**

Run:

```bash
pytest tests/test_database_control_api.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add app/routes/database.py tests/test_database_control_api.py
git commit -m "feat: add structured row controls"
```

---

### Task 3: Column Schema Controls

**Files:**
- Modify: `app/routes/database.py`
- Modify: `tests/test_database_control_api.py`

- [ ] **Step 1: Add request models**

```python
class ColumnCreateRequest(BaseModel):
    name: str
    data_type: str
    nullable: bool = True
    default: Optional[str] = None


class ColumnRenameRequest(BaseModel):
    new_name: str


class ColumnNullableRequest(BaseModel):
    nullable: bool


class ColumnDefaultRequest(BaseModel):
    default: Optional[str] = None


class ColumnTypeRequest(BaseModel):
    data_type: str
```

- [ ] **Step 2: Add column endpoint validation test**

Append:

```python
def test_add_column_rejects_invalid_type(monkeypatch):
    class FakeInspector:
        def has_table(self, table_name, schema=None):
            return True

        def get_columns(self, table_name, schema=None):
            return [{"name": "id", "type": "INTEGER"}]

    monkeypatch.setattr(database, "inspect", lambda engine: FakeInspector())
    monkeypatch.setattr(database, "get_db_engine", lambda: object())

    response = client.post(
        "/api/database/tables/sample_table/columns",
        json={"name": "payload", "data_type": "jsonb"},
    )
    assert response.status_code == 400
```

- [ ] **Step 3: Add schema endpoints**

Add after column metadata endpoint:

```python
@router.post("/tables/{table_name}/columns")
async def add_column(table_name: str, body: ColumnCreateRequest):
    table_name = _validate_identifier(table_name, "table name")
    column_name = _validate_identifier(body.name, "column name")
    sql_type = _normalize_column_type(body.data_type)
    engine = get_db_engine()
    inspector = inspect(engine)
    existing = _get_column_names(inspector, table_name)
    if column_name in existing:
        raise HTTPException(status_code=409, detail=f"Column '{column_name}' already exists")
    nullable_sql = "" if body.nullable else " NOT NULL"
    default_sql = " DEFAULT :default_value" if body.default is not None else ""
    params = {"default_value": body.default} if body.default is not None else {}

    with engine.connect() as conn:
        conn.execute(text(f'ALTER TABLE vector."{table_name}" ADD COLUMN "{column_name}" {sql_type}{default_sql}{nullable_sql}'), params)
        conn.commit()

    _log_change(engine, table_name, "column_add", {"column": column_name, "type": sql_type})
    return {"success": True, "message": f"Column {column_name} added"}


@router.put("/tables/{table_name}/columns/{column_name}/rename")
async def rename_column(table_name: str, column_name: str, body: ColumnRenameRequest):
    table_name = _validate_identifier(table_name, "table name")
    column_name = _validate_identifier(column_name, "column name")
    new_name = _validate_identifier(body.new_name, "new column name")
    engine = get_db_engine()
    inspector = inspect(engine)
    columns = _get_column_names(inspector, table_name)
    if column_name not in columns:
        raise HTTPException(status_code=404, detail=f"Column '{column_name}' not found")
    if new_name in columns:
        raise HTTPException(status_code=409, detail=f"Column '{new_name}' already exists")

    with engine.connect() as conn:
        conn.execute(text(f'ALTER TABLE vector."{table_name}" RENAME COLUMN "{column_name}" TO "{new_name}"'))
        conn.execute(
            text("UPDATE metadata.column_descriptions SET column_name = :new WHERE table_name = :table AND column_name = :old"),
            {"new": new_name, "table": table_name, "old": column_name},
        )
        conn.commit()

    _log_change(engine, table_name, "column_rename", {"old_name": column_name, "new_name": new_name})
    return {"success": True, "message": f"Column {column_name} renamed to {new_name}"}


@router.put("/tables/{table_name}/columns/{column_name}/nullable")
async def set_column_nullable(table_name: str, column_name: str, body: ColumnNullableRequest):
    table_name = _validate_identifier(table_name, "table name")
    column_name = _validate_identifier(column_name, "column name")
    engine = get_db_engine()
    inspector = inspect(engine)
    if column_name not in _get_column_names(inspector, table_name):
        raise HTTPException(status_code=404, detail=f"Column '{column_name}' not found")
    action = "DROP NOT NULL" if body.nullable else "SET NOT NULL"

    with engine.connect() as conn:
        conn.execute(text(f'ALTER TABLE vector."{table_name}" ALTER COLUMN "{column_name}" {action}'))
        conn.commit()

    _log_change(engine, table_name, "column_nullable", {"column": column_name, "nullable": body.nullable})
    return {"success": True, "message": f"Column {column_name} nullable set to {body.nullable}"}


@router.put("/tables/{table_name}/columns/{column_name}/default")
async def set_column_default(table_name: str, column_name: str, body: ColumnDefaultRequest):
    table_name = _validate_identifier(table_name, "table name")
    column_name = _validate_identifier(column_name, "column name")
    engine = get_db_engine()
    inspector = inspect(engine)
    if column_name not in _get_column_names(inspector, table_name):
        raise HTTPException(status_code=404, detail=f"Column '{column_name}' not found")

    with engine.connect() as conn:
        if body.default is None:
            conn.execute(text(f'ALTER TABLE vector."{table_name}" ALTER COLUMN "{column_name}" DROP DEFAULT'))
        else:
            conn.execute(text(f'ALTER TABLE vector."{table_name}" ALTER COLUMN "{column_name}" SET DEFAULT :default_value'), {"default_value": body.default})
        conn.commit()

    _log_change(engine, table_name, "column_default", {"column": column_name, "has_default": body.default is not None})
    return {"success": True, "message": f"Column {column_name} default updated"}


@router.put("/tables/{table_name}/columns/{column_name}/type")
async def set_column_type(table_name: str, column_name: str, body: ColumnTypeRequest):
    table_name = _validate_identifier(table_name, "table name")
    column_name = _validate_identifier(column_name, "column name")
    sql_type = _normalize_column_type(body.data_type)
    engine = get_db_engine()
    inspector = inspect(engine)
    if column_name not in _get_column_names(inspector, table_name):
        raise HTTPException(status_code=404, detail=f"Column '{column_name}' not found")

    with engine.connect() as conn:
        conn.execute(text(f'ALTER TABLE vector."{table_name}" ALTER COLUMN "{column_name}" TYPE {sql_type} USING "{column_name}"::{sql_type}'))
        conn.commit()

    _log_change(engine, table_name, "column_type", {"column": column_name, "type": sql_type})
    return {"success": True, "message": f"Column {column_name} type changed"}


@router.delete("/tables/{table_name}/columns/{column_name}")
async def drop_column(table_name: str, column_name: str):
    table_name = _validate_identifier(table_name, "table name")
    column_name = _validate_identifier(column_name, "column name")
    engine = get_db_engine()
    inspector = inspect(engine)
    if column_name not in _get_column_names(inspector, table_name):
        raise HTTPException(status_code=404, detail=f"Column '{column_name}' not found")

    with engine.connect() as conn:
        conn.execute(text(f'ALTER TABLE vector."{table_name}" DROP COLUMN "{column_name}"'))
        conn.execute(
            text("DELETE FROM metadata.column_descriptions WHERE table_name = :table AND column_name = :column"),
            {"table": table_name, "column": column_name},
        )
        conn.commit()

    _log_change(engine, table_name, "column_drop", {"column": column_name})
    return {"success": True, "message": f"Column {column_name} dropped"}
```

- [ ] **Step 4: Run schema tests**

Run:

```bash
pytest tests/test_database_control_api.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add app/routes/database.py tests/test_database_control_api.py
git commit -m "feat: add structured column controls"
```

---

### Task 4: Index and Table Operation Controls

**Files:**
- Modify: `app/routes/database.py`
- Modify: `tests/test_database_control_api.py`

- [ ] **Step 1: Add models**

```python
class IndexCreateRequest(BaseModel):
    name: Optional[str] = None
    columns: List[str]
    method: str = "btree"


class TableCloneRequest(BaseModel):
    new_name: str
    include_data: bool = True


class TableCreateRequest(BaseModel):
    table_name: str
    columns: List[ColumnCreateRequest]
```

- [ ] **Step 2: Add endpoints**

Add after table stats:

```python
@router.get("/tables/{table_name}/indexes")
async def list_indexes(table_name: str):
    table_name = _validate_identifier(table_name, "table name")
    engine = get_db_engine()
    inspector = inspect(engine)
    _get_vector_columns(inspector, table_name)
    return {"success": True, "indexes": inspector.get_indexes(table_name, schema="vector")}


@router.post("/tables/{table_name}/indexes")
async def create_index(table_name: str, body: IndexCreateRequest):
    table_name = _validate_identifier(table_name, "table name")
    if body.method not in ("btree", "gist"):
        raise HTTPException(status_code=400, detail="Index method must be btree or gist")
    if not body.columns:
        raise HTTPException(status_code=400, detail="At least one index column is required")
    engine = get_db_engine()
    inspector = inspect(engine)
    col_names = _get_column_names(inspector, table_name)
    for col in body.columns:
        if col not in col_names:
            raise HTTPException(status_code=400, detail=f"Unknown column: {col}")
    index_name = body.name or f"idx_{table_name}_{'_'.join(body.columns)}"
    index_name = _validate_identifier(index_name[:59], "index name")
    col_sql = ", ".join(f'"{c}"' for c in body.columns)

    with engine.connect() as conn:
        conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{index_name}" ON vector."{table_name}" USING {body.method.upper()} ({col_sql})'))
        conn.commit()

    _log_change(engine, table_name, "index_create", {"index": index_name, "columns": body.columns, "method": body.method})
    return {"success": True, "index_name": index_name}


@router.delete("/tables/{table_name}/indexes/{index_name}")
async def drop_index(table_name: str, index_name: str):
    table_name = _validate_identifier(table_name, "table name")
    index_name = _validate_identifier(index_name, "index name")
    engine = get_db_engine()
    inspector = inspect(engine)
    _get_vector_columns(inspector, table_name)

    with engine.connect() as conn:
        conn.execute(text(f'DROP INDEX IF EXISTS vector."{index_name}"'))
        conn.commit()

    _log_change(engine, table_name, "index_drop", {"index": index_name})
    return {"success": True, "message": f"Index {index_name} dropped"}


@router.post("/tables/{table_name}/clone")
async def clone_table(table_name: str, body: TableCloneRequest):
    table_name = _validate_identifier(table_name, "table name")
    new_name = _validate_identifier(body.new_name, "new table name")
    engine = get_db_engine()
    inspector = inspect(engine)
    _get_vector_columns(inspector, table_name)
    if inspector.has_table(new_name, schema="vector"):
        raise HTTPException(status_code=409, detail=f"Table '{new_name}' already exists")
    data_sql = "WITH DATA" if body.include_data else "WITH NO DATA"

    with engine.connect() as conn:
        conn.execute(text(f'CREATE TABLE vector."{new_name}" AS TABLE vector."{table_name}" {data_sql}'))
        conn.execute(
            text("""
                INSERT INTO metadata.table_descriptions (table_name, description, category, source, updated_by)
                SELECT :new_name, CONCAT('Clone of ', table_name, ': ', COALESCE(description, '')), category, source, 'api_user'
                FROM metadata.table_descriptions
                WHERE table_name = :old_name
                ON CONFLICT (table_name) DO NOTHING
            """),
            {"new_name": new_name, "old_name": table_name},
        )
        conn.commit()

    _log_change(engine, new_name, "table_clone", {"source_table": table_name, "include_data": body.include_data})
    return {"success": True, "table_name": new_name}


@router.post("/tables/{table_name}/truncate")
async def truncate_table(table_name: str):
    table_name = _validate_identifier(table_name, "table name")
    engine = get_db_engine()
    inspector = inspect(engine)
    _get_vector_columns(inspector, table_name)

    with engine.connect() as conn:
        conn.execute(text(f'TRUNCATE TABLE vector."{table_name}"'))
        conn.execute(text("UPDATE metadata.table_descriptions SET row_count = 0, updated_at = CURRENT_TIMESTAMP WHERE table_name = :table"), {"table": table_name})
        conn.commit()

    _log_change(engine, table_name, "table_truncate", {})
    return {"success": True, "message": f"Table {table_name} truncated"}


@router.get("/tables/{table_name}/export")
async def export_table(table_name: str, limit: int = Query(100000, ge=1, le=1000000)):
    table_name = _validate_identifier(table_name, "table name")
    engine = get_db_engine()
    inspector = inspect(engine)
    cols = _get_vector_columns(inspector, table_name)
    select_parts = []
    for col in cols:
        if "geometry" in str(col["type"]).lower():
            select_parts.append(f'ST_AsText("{col["name"]}") AS "{col["name"]}"')
        else:
            select_parts.append(f'"{col["name"]}"')

    with engine.connect() as conn:
        result = conn.execute(text(f'SELECT {", ".join(select_parts)} FROM vector."{table_name}" LIMIT :limit'), {"limit": limit})
        rows = result.fetchall()
        headers = list(result.keys())

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return JSONResponse({"success": True, "filename": f"{table_name}.csv", "csv": output.getvalue()})


@router.post("/tables/create")
async def create_empty_table(body: TableCreateRequest):
    table_name = _validate_identifier(body.table_name, "table name")
    if not body.columns:
        raise HTTPException(status_code=400, detail="At least one column is required")
    engine = get_db_engine()
    inspector = inspect(engine)
    if inspector.has_table(table_name, schema="vector"):
        raise HTTPException(status_code=409, detail=f"Table '{table_name}' already exists")

    seen = set()
    col_defs = []
    for col in body.columns:
        col_name = _validate_identifier(col.name, "column name")
        if col_name in seen:
            raise HTTPException(status_code=400, detail=f"Duplicate column: {col_name}")
        seen.add(col_name)
        sql_type = _normalize_column_type(col.data_type)
        nullable_sql = "" if col.nullable else " NOT NULL"
        col_defs.append(f'"{col_name}" {sql_type}{nullable_sql}')

    with engine.connect() as conn:
        conn.execute(text(f'CREATE TABLE vector."{table_name}" ({", ".join(col_defs)})'))
        conn.commit()

    _log_change(engine, table_name, "table_create", {"columns": list(seen)})
    return {"success": True, "table_name": table_name}
```

- [ ] **Step 3: Run backend tests**

Run:

```bash
pytest tests/test_database_control_api.py -q
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add app/routes/database.py tests/test_database_control_api.py
git commit -m "feat: add structured table and index controls"
```

---

### Task 5: Database Inspector UI Controls

**Files:**
- Modify: `frontend/database-inspector.html`

- [ ] **Step 1: Add detail sub-tabs markup in `renderDetails`**

Replace the tail of `renderDetails`:

```javascript
h += '<div id="previewSection"></div><div id="statsSection"></div>';
pane.innerHTML = h;
```

with:

```javascript
h += `
  <div class="d-section fade-in">
    <div class="tab-bar" style="margin:0 0 14px;padding:0;border:none">
      <div class="tab active table-subtab" data-subtab="data" onclick="switchTableSubtab('data','${t.table_name}')"><i class="fas fa-table"></i> Data</div>
      <div class="tab table-subtab" data-subtab="columns" onclick="switchTableSubtab('columns','${t.table_name}')"><i class="fas fa-columns"></i> Columns</div>
      <div class="tab table-subtab" data-subtab="indexes" onclick="switchTableSubtab('indexes','${t.table_name}')"><i class="fas fa-bolt"></i> Indexes</div>
      <div class="tab table-subtab" data-subtab="ops" onclick="switchTableSubtab('ops','${t.table_name}')"><i class="fas fa-toolbox"></i> Operations</div>
    </div>
    <div id="tableControlPane"></div>
  </div>`;
pane.innerHTML = h;
loadRows(t.table_name);
```

- [ ] **Step 2: Add UI JavaScript functions**

Add before `// ── OVERPASS IMPORT TAB ──`:

```javascript
let currentRowsPage = 1;

function switchTableSubtab(tab, tableName) {
  document.querySelectorAll('.table-subtab').forEach(x => x.classList.toggle('active', x.dataset.subtab === tab));
  if (tab === 'data') loadRows(tableName);
  if (tab === 'columns') renderColumnControls(tableName);
  if (tab === 'indexes') loadIndexes(tableName);
  if (tab === 'ops') renderTableOps(tableName);
}

async function loadRows(tableName, page = 1) {
  currentRowsPage = page;
  const pane = document.getElementById('tableControlPane');
  pane.innerHTML = '<div class="empty"><div class="spinner"></div>Loading rows...</div>';
  const r = await fetch(`${API}/tables/${tableName}/rows?page=${page}&per_page=50`);
  const d = await r.json();
  if (!d.success) { pane.innerHTML = '<p style="color:var(--red)">Could not load rows.</p>'; return; }
  const th = d.columns.map(c => `<th>${c}</th>`).join('') + '<th>Actions</th>';
  const rows = d.rows.map(row => {
    const ref = JSON.stringify(buildRowRef(row, d.pk_columns)).replace(/"/g, '&quot;');
    const cells = d.columns.map(c => `<td title="${String(row[c] ?? '')}">${String(row[c] ?? '').substring(0, 80)}</td>`).join('');
    return `<tr>${cells}<td><button class="btn" onclick="openRowEditor('${tableName}', '${encodeURIComponent(JSON.stringify(row))}', '${encodeURIComponent(JSON.stringify(d.pk_columns))}')"><i class="fas fa-edit"></i></button><button class="btn" onclick="duplicateRow('${tableName}', ${ref})"><i class="fas fa-copy"></i></button><button class="btn danger" onclick="deleteRow('${tableName}', ${ref})"><i class="fas fa-trash"></i></button></td></tr>`;
  }).join('');
  pane.innerHTML = `
    <div style="display:flex;justify-content:space-between;gap:8px;margin-bottom:10px">
      <button class="btn primary" onclick="openRowEditor('${tableName}', '', '${encodeURIComponent(JSON.stringify(d.pk_columns))}')"><i class="fas fa-plus"></i> Add Row</button>
      <div style="font-size:12px;color:var(--text2)">Page ${d.page} of ${d.total_pages || 1} · ${d.total.toLocaleString()} rows</div>
    </div>
    <div class="preview-wrap"><table class="preview-table"><thead><tr>${th}</tr></thead><tbody>${rows}</tbody></table></div>
    <div class="pagination">
      <button class="btn" ${d.page <= 1 ? 'disabled' : ''} onclick="loadRows('${tableName}', ${d.page - 1})"><i class="fas fa-chevron-left"></i></button>
      <button class="btn" ${d.page >= d.total_pages ? 'disabled' : ''} onclick="loadRows('${tableName}', ${d.page + 1})"><i class="fas fa-chevron-right"></i></button>
    </div>`;
}

function buildRowRef(row, pkColumns) {
  if (pkColumns && pkColumns.length) {
    const ref = {};
    pkColumns.forEach(c => ref[c] = row[c]);
    return ref;
  }
  return { _row_ref: row._row_ref };
}

function renderColumnControls(tableName) {
  const t = tables.find(x => x.table_name === tableName);
  const rows = (t?.columns || []).map(c => `<tr><td>${c.name}</td><td>${c.type}</td><td><button class="btn" onclick="renameColumnPrompt('${tableName}','${c.name}')">Rename</button><button class="btn danger" onclick="dropColumn('${tableName}','${c.name}')">Drop</button></td></tr>`).join('');
  document.getElementById('tableControlPane').innerHTML = `
    <div style="display:flex;gap:8px;margin-bottom:12px">
      <input id="newColName" placeholder="column_name">
      <select id="newColType"><option>text</option><option>integer</option><option>double</option><option>boolean</option><option>date</option><option>timestamp</option><option>geometry</option></select>
      <button class="btn primary" onclick="addColumn('${tableName}')">Add Column</button>
    </div>
    <div class="preview-wrap"><table class="preview-table"><thead><tr><th>Name</th><th>Type</th><th>Actions</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

async function addColumn(tableName) {
  const name = document.getElementById('newColName').value.trim();
  const data_type = document.getElementById('newColType').value;
  const r = await fetch(`${API}/tables/${tableName}/columns`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ name, data_type }) });
  const d = await r.json();
  if (!d.success) { alert(d.detail || 'Could not add column'); return; }
  await selectTable(tableName);
}

async function renameColumnPrompt(tableName, columnName) {
  const new_name = prompt('New column name', columnName);
  if (!new_name || new_name === columnName) return;
  const r = await fetch(`${API}/tables/${tableName}/columns/${columnName}/rename`, { method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ new_name }) });
  const d = await r.json();
  if (!d.success) { alert(d.detail || 'Could not rename column'); return; }
  await selectTable(tableName);
}

async function dropColumn(tableName, columnName) {
  if (!confirm(`Drop column ${columnName}?`)) return;
  const r = await fetch(`${API}/tables/${tableName}/columns/${columnName}`, { method:'DELETE' });
  const d = await r.json();
  if (!d.success) { alert(d.detail || 'Could not drop column'); return; }
  await selectTable(tableName);
}

async function loadIndexes(tableName) {
  const pane = document.getElementById('tableControlPane');
  pane.innerHTML = '<div class="empty"><div class="spinner"></div>Loading indexes...</div>';
  const r = await fetch(`${API}/tables/${tableName}/indexes`);
  const d = await r.json();
  const rows = (d.indexes || []).map(i => `<tr><td>${i.name}</td><td>${(i.column_names || []).join(', ')}</td><td><button class="btn danger" onclick="dropIndex('${tableName}','${i.name}')">Drop</button></td></tr>`).join('');
  pane.innerHTML = `<div class="preview-wrap"><table class="preview-table"><thead><tr><th>Name</th><th>Columns</th><th>Actions</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

async function dropIndex(tableName, indexName) {
  const r = await fetch(`${API}/tables/${tableName}/indexes/${indexName}`, { method:'DELETE' });
  const d = await r.json();
  if (!d.success) { alert(d.detail || 'Could not drop index'); return; }
  await loadIndexes(tableName);
}

function renderTableOps(tableName) {
  document.getElementById('tableControlPane').innerHTML = `
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="btn" onclick="cloneTablePrompt('${tableName}')"><i class="fas fa-copy"></i> Clone Table</button>
      <button class="btn danger" onclick="truncateTable('${tableName}')"><i class="fas fa-eraser"></i> Truncate</button>
      <button class="btn" onclick="exportTable('${tableName}')"><i class="fas fa-download"></i> Export CSV</button>
    </div>`;
}
```

- [ ] **Step 3: Add minimal row mutation UI functions**

Add below `buildRowRef`:

```javascript
function openRowEditor(tableName, encodedRow, encodedPkCols) {
  const row = encodedRow ? JSON.parse(decodeURIComponent(encodedRow)) : {};
  const pkCols = JSON.parse(decodeURIComponent(encodedPkCols || '%5B%5D'));
  const editable = Object.keys(row).filter(k => k !== '_row_ref' && !pkCols.includes(k));
  const fields = editable.length ? editable : ['name'];
  const html = fields.map(k => `<div class="form-group"><label>${k}</label><input data-row-field="${k}" value="${String(row[k] ?? '').replace(/"/g, '&quot;')}"></div>`).join('');
  const ref = JSON.stringify(buildRowRef(row, pkCols)).replace(/"/g, '&quot;');
  const modal = document.createElement('div');
  modal.className = 'modal-bg active';
  modal.id = 'rowEditorModal';
  modal.innerHTML = `<div class="modal"><h3>${encodedRow ? 'Edit Row' : 'Add Row'}</h3>${html}<div class="modal-actions"><button class="btn" onclick="document.getElementById('rowEditorModal').remove()">Cancel</button><button class="btn primary" onclick="saveRow('${tableName}', ${encodedRow ? ref : 'null'})">Save</button></div></div>`;
  document.body.appendChild(modal);
}

async function saveRow(tableName, rowRef) {
  const values = {};
  document.querySelectorAll('[data-row-field]').forEach(input => values[input.dataset.rowField] = input.value);
  const url = `${API}/tables/${tableName}/rows`;
  const options = rowRef
    ? { method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ row_ref: rowRef, values }) }
    : { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ values }) };
  const r = await fetch(url, options);
  const d = await r.json();
  if (!d.success) { alert(d.detail || 'Could not save row'); return; }
  document.getElementById('rowEditorModal')?.remove();
  await loadRows(tableName, currentRowsPage);
}

async function deleteRow(tableName, rowRef) {
  if (!confirm('Delete this row?')) return;
  const r = await fetch(`${API}/tables/${tableName}/rows`, { method:'DELETE', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ row_ref: rowRef }) });
  const d = await r.json();
  if (!d.success) { alert(d.detail || 'Could not delete row'); return; }
  await loadRows(tableName, currentRowsPage);
}

async function duplicateRow(tableName, rowRef) {
  const r = await fetch(`${API}/tables/${tableName}/rows/duplicate`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ row_ref: rowRef }) });
  const d = await r.json();
  if (!d.success) { alert(d.detail || 'Could not duplicate row'); return; }
  await loadRows(tableName, currentRowsPage);
}

async function cloneTablePrompt(tableName) {
  const new_name = prompt('Clone table as', `${tableName}_copy`);
  if (!new_name) return;
  const r = await fetch(`${API}/tables/${tableName}/clone`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ new_name, include_data: true }) });
  const d = await r.json();
  if (!d.success) { alert(d.detail || 'Could not clone table'); return; }
  await loadTables();
}

async function truncateTable(tableName) {
  if (!confirm(`Truncate all rows in ${tableName}?`)) return;
  const r = await fetch(`${API}/tables/${tableName}/truncate`, { method:'POST' });
  const d = await r.json();
  if (!d.success) { alert(d.detail || 'Could not truncate table'); return; }
  await selectTable(tableName);
}

async function exportTable(tableName) {
  const r = await fetch(`${API}/tables/${tableName}/export`);
  const d = await r.json();
  if (!d.success) { alert(d.detail || 'Could not export table'); return; }
  const blob = new Blob([d.csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = d.filename;
  a.click();
  URL.revokeObjectURL(url);
}
```

- [ ] **Step 4: Run a smoke check**

Run:

```bash
python -m py_compile app/routes/database.py
```

Expected: no output and exit code 0.

- [ ] **Step 5: Commit**

```bash
git add frontend/database-inspector.html app/routes/database.py
git commit -m "feat: add structured database inspector controls"
```

---

### Task 6: Verification

**Files:**
- Verify: `app/routes/database.py`
- Verify: `frontend/database-inspector.html`
- Verify: `tests/test_database_control_api.py`

- [ ] **Step 1: Run targeted tests**

```bash
pytest tests/test_database_control_api.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run existing API tests**

```bash
pytest tests/test_api.py -q
```

Expected: pass or fail only for pre-existing environment/database dependency issues. Record exact failures.

- [ ] **Step 3: Compile backend**

```bash
python -m py_compile app/routes/database.py
```

Expected: no output.

- [ ] **Step 4: Start dev server**

```bash
uvicorn app.main:app --reload --port 8000
```

Expected: app starts and serves `/database-inspector`.

- [ ] **Step 5: Manual UI smoke test**

Open `http://localhost:8000/database-inspector` and verify:

- Tables load.
- Selecting a table shows `Data`, `Columns`, `Indexes`, `Operations`.
- `Data` loads rows.
- `Columns` displays columns and can reject invalid column names/types.
- `Indexes` displays indexes.
- `Operations` renders clone/truncate/export buttons.

- [ ] **Step 6: Commit verification fixes if needed**

```bash
git add app/routes/database.py frontend/database-inspector.html tests/test_database_control_api.py
git commit -m "fix: stabilize structured database controls"
```

---

## Self-Review

Spec coverage:

- Structured UI actions only: covered by typed endpoints and no SQL console.
- Row control: covered by Task 2 and Task 5.
- Column/schema control: covered by Task 3 and Task 5.
- Table control: covered by Task 4 and Task 5.
- Index control: covered by Task 4 and Task 5.
- Existing map/spatial preview: intentionally out of scope.
- Safety/auth work: intentionally out of scope per user instruction.

Placeholder scan:

- No TBD/TODO placeholders.
- Every endpoint has concrete request/response behavior.
- Every task has explicit commands and expected results.

Type consistency:

- Request model names used by endpoint signatures are defined before use.
- UI function names are unique and match onclick calls.
- Endpoint paths match the API contract section.
