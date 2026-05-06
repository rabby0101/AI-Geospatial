import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.routes import database

client = TestClient(app)


def test_validate_identifier_accepts_simple_names():
    assert database._validate_identifier("osm_hospitals", "table") == "osm_hospitals"
    assert database._validate_identifier("name_2", "column") == "name_2"


@pytest.mark.parametrize("value", ["", "a-b", "AName", "x;drop", "table.name", " name", "a" * 64])
def test_validate_identifier_rejects_unsafe_names(value):
    with pytest.raises(HTTPException) as exc:
        database._validate_identifier(value, "table")
    assert exc.value.status_code == 400


@pytest.mark.parametrize("column_name", ["bad-name", 'bad"name'])
def test_validate_structured_control_columns_rejects_unsafe_inspected_names(column_name):
    with pytest.raises(HTTPException) as exc:
        database._validate_structured_control_columns([{"name": "id"}, {"name": column_name}])

    assert exc.value.status_code == 400
    assert column_name in exc.value.detail


def test_normalize_column_type_accepts_allowlisted_types():
    assert database._normalize_column_type("text") == "TEXT"
    assert database._normalize_column_type("INTEGER") == "INTEGER"
    assert database._normalize_column_type("geometry") == "geometry(Geometry, 4326)"


def test_normalize_column_type_rejects_unlisted_types():
    with pytest.raises(HTTPException) as exc:
        database._normalize_column_type("serial primary key")
    assert exc.value.status_code == 400


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


def test_row_insert_rejects_unsafe_existing_column_before_sql(monkeypatch):
    class FakeInspector:
        def has_table(self, table_name, schema=None):
            return table_name == "sample_table" and schema == "vector"

        def get_columns(self, table_name, schema=None):
            return [{"name": "id", "type": "INTEGER"}, {"name": "bad-name", "type": "TEXT"}]

    class FailingEngine:
        def connect(self):
            raise AssertionError("SQL execution should not be reached")

    monkeypatch.setattr(database, "inspect", lambda engine: FakeInspector())
    monkeypatch.setattr(database, "get_db_engine", lambda: FailingEngine())

    response = client.post("/api/database/tables/sample_table/rows", json={"values": {"id": 1}})
    assert response.status_code == 400
    assert "Unsupported column name(s)" in response.json()["detail"]
    assert "bad-name" in response.json()["detail"]


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


def test_add_column_can_create_description_metadata(monkeypatch):
    captured = []

    class FakeInspector:
        def has_table(self, table_name, schema=None):
            return table_name == "sample_table" and schema == "vector"

        def get_columns(self, table_name, schema=None):
            return [{"name": "id", "type": "INTEGER"}]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            captured.append((str(statement), params))

        def commit(self):
            captured.append(("COMMIT", None))

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(database, "inspect", lambda engine: FakeInspector())
    monkeypatch.setattr(database, "get_db_engine", lambda: FakeEngine())

    response = client.post(
        "/api/database/tables/sample_table/columns",
        json={
            "name": "display_name",
            "data_type": "text",
            "description": "User-facing display label",
            "english_name": "Display name",
            "example_value": "Central Station",
        },
    )

    assert response.status_code == 200
    assert any(
        'ALTER TABLE vector."sample_table" ADD COLUMN "display_name" TEXT' in sql
        for sql, _ in captured
    )
    metadata_inserts = [
        params
        for sql, params in captured
        if "INSERT INTO metadata.column_descriptions" in sql
    ]
    assert metadata_inserts
    assert metadata_inserts[0] == {
        "table_name": "sample_table",
        "column_name": "display_name",
        "description": "User-facing display label",
        "english_name": "Display name",
        "example_value": "Central Station",
        "is_german": False,
        "data_type": "TEXT",
        "updated_by": "api_user",
    }


def test_set_column_type_updates_column_metadata(monkeypatch):
    captured = []

    class FakeInspector:
        def has_table(self, table_name, schema=None):
            return table_name == "sample_table" and schema == "vector"

        def get_columns(self, table_name, schema=None):
            return [{"name": "id", "type": "INTEGER"}, {"name": "payload", "type": "TEXT"}]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            captured.append((str(statement), params))

        def commit(self):
            captured.append(("COMMIT", None))

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(database, "inspect", lambda engine: FakeInspector())
    monkeypatch.setattr(database, "get_db_engine", lambda: FakeEngine())

    response = client.put(
        "/api/database/tables/sample_table/columns/payload/type",
        json={"data_type": "integer"},
    )

    assert response.status_code == 200
    assert any(
        'ALTER TABLE vector."sample_table" ALTER COLUMN "payload" TYPE INTEGER' in sql
        for sql, _ in captured
    )
    metadata_updates = [
        (sql, params)
        for sql, params in captured
        if "UPDATE metadata.column_descriptions" in sql
    ]
    assert metadata_updates
    assert metadata_updates[0][1] == {
        "table": "sample_table",
        "column": "payload",
        "data_type": "INTEGER",
    }


def test_create_index_rejects_unknown_column(monkeypatch):
    class FakeInspector:
        def has_table(self, table_name, schema=None):
            return table_name == "sample_table" and schema == "vector"

        def get_columns(self, table_name, schema=None):
            return [{"name": "id", "type": "INTEGER"}, {"name": "name", "type": "TEXT"}]

    class FailingEngine:
        def connect(self):
            raise AssertionError("SQL execution should not be reached")

    monkeypatch.setattr(database, "inspect", lambda engine: FakeInspector())
    monkeypatch.setattr(database, "get_db_engine", lambda: FailingEngine())

    response = client.post(
        "/api/database/tables/sample_table/indexes",
        json={"columns": ["missing_column"]},
    )

    assert response.status_code == 400
    assert "Unknown column" in response.json()["detail"]


def test_create_index_rejects_invalid_method(monkeypatch):
    class FakeInspector:
        def has_table(self, table_name, schema=None):
            return table_name == "sample_table" and schema == "vector"

        def get_columns(self, table_name, schema=None):
            return [{"name": "id", "type": "INTEGER"}]

    class FailingEngine:
        def connect(self):
            raise AssertionError("SQL execution should not be reached")

    monkeypatch.setattr(database, "inspect", lambda engine: FakeInspector())
    monkeypatch.setattr(database, "get_db_engine", lambda: FailingEngine())

    response = client.post(
        "/api/database/tables/sample_table/indexes",
        json={"columns": ["id"], "method": "hash"},
    )

    assert response.status_code == 400
    assert "Unsupported index method" in response.json()["detail"]


def test_create_index_rejects_schema_scoped_name_collision(monkeypatch):
    captured = []

    class FakeInspector:
        def has_table(self, table_name, schema=None):
            return table_name == "sample_table" and schema == "vector"

        def get_columns(self, table_name, schema=None):
            return [{"name": "id", "type": "INTEGER"}]

    class FakeResult:
        def fetchone(self):
            return ("other_table", ["id"])

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            captured.append((str(statement), params))
            if "pg_class" in str(statement):
                return FakeResult()
            raise AssertionError("CREATE INDEX should not be reached")

        def commit(self):
            captured.append(("COMMIT", None))

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(database, "inspect", lambda engine: FakeInspector())
    monkeypatch.setattr(database, "get_db_engine", lambda: FakeEngine())

    response = client.post(
        "/api/database/tables/sample_table/indexes",
        json={"name": "idx_collision", "columns": ["id"]},
    )

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]
    assert "other_table" in response.json()["detail"]
    assert not any("CREATE INDEX" in sql for sql, _ in captured)


def test_create_index_rejects_non_index_relation_name_collision(monkeypatch):
    captured = []

    class FakeInspector:
        def has_table(self, table_name, schema=None):
            return table_name == "sample_table" and schema == "vector"

        def get_columns(self, table_name, schema=None):
            return [{"name": "id", "type": "INTEGER"}]

    class FakeResult:
        def fetchone(self):
            return (None, "r")

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            captured.append((str(statement), params))
            if "pg_class" in str(statement):
                return FakeResult()
            raise AssertionError("CREATE INDEX should not be reached")

        def commit(self):
            captured.append(("COMMIT", None))

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(database, "inspect", lambda engine: FakeInspector())
    monkeypatch.setattr(database, "get_db_engine", lambda: FakeEngine())

    response = client.post(
        "/api/database/tables/sample_table/indexes",
        json={"name": "sample_table", "columns": ["id"]},
    )

    assert response.status_code == 409
    assert "already exists in schema" in response.json()["detail"]
    assert not any("CREATE INDEX" in sql for sql, _ in captured)


def test_generated_index_name_hash_suffix_avoids_long_name_collision():
    table_name = "a" * 50
    common_column = "b" * 50
    first_name = database._generated_index_name(table_name, [common_column, "first_column"])
    second_name = database._generated_index_name(table_name, [common_column, "second_column"])

    assert len(first_name) <= 63
    assert len(second_name) <= 63
    assert first_name.startswith("idx_")
    assert second_name.startswith("idx_")
    assert first_name[-9] == "_"
    assert second_name[-9] == "_"
    assert first_name != second_name


def test_preview_rejects_unsafe_table_name_before_sql(monkeypatch):
    class FailingEngine:
        def connect(self):
            raise AssertionError("SQL execution should not be reached")

    monkeypatch.setattr(database, "get_db_engine", lambda: FailingEngine())

    response = client.get("/api/database/tables/SampleTable/preview")

    assert response.status_code == 400
    assert "Invalid table name" in response.json()["detail"]


def test_preview_rejects_unsafe_inspected_column_before_sql(monkeypatch):
    captured = []

    class FakeInspector:
        def has_table(self, table_name, schema=None):
            return table_name == "sample_table" and schema == "vector"

        def get_columns(self, table_name, schema=None):
            return [{"name": "id", "type": "INTEGER"}, {"name": "bad-name", "type": "TEXT"}]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            captured.append((str(statement), params))
            raise AssertionError("SQL execution should not be reached")

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(database, "inspect", lambda engine: FakeInspector())
    monkeypatch.setattr(database, "get_db_engine", lambda: FakeEngine())

    response = client.get("/api/database/tables/sample_table/preview")

    assert response.status_code == 400
    assert "Unsupported column name(s)" in response.json()["detail"]
    assert "bad-name" in response.json()["detail"]
    assert not captured


def test_stats_rejects_unsafe_inspected_column_before_sql(monkeypatch):
    captured = []

    class FakeInspector:
        def has_table(self, table_name, schema=None):
            return table_name == "sample_table" and schema == "vector"

        def get_columns(self, table_name, schema=None):
            return [{"name": "id", "type": "INTEGER"}, {"name": "bad-name", "type": "TEXT"}]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            captured.append((str(statement), params))
            raise AssertionError("SQL execution should not be reached")

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(database, "inspect", lambda engine: FakeInspector())
    monkeypatch.setattr(database, "get_db_engine", lambda: FakeEngine())

    response = client.get("/api/database/tables/sample_table/stats")

    assert response.status_code == 400
    assert "Unsupported column name(s)" in response.json()["detail"]
    assert "bad-name" in response.json()["detail"]
    assert not captured


def test_drop_index_rejects_index_not_belonging_to_table(monkeypatch):
    captured = []

    class FakeInspector:
        def has_table(self, table_name, schema=None):
            return table_name == "sample_table" and schema == "vector"

        def get_columns(self, table_name, schema=None):
            return [{"name": "id", "type": "INTEGER"}]

        def get_indexes(self, table_name, schema=None):
            assert table_name == "sample_table"
            assert schema == "vector"
            return [{"name": "idx_sample_table_id", "column_names": ["id"]}]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            captured.append((str(statement), params))

        def commit(self):
            captured.append(("COMMIT", None))

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(database, "inspect", lambda engine: FakeInspector())
    monkeypatch.setattr(database, "get_db_engine", lambda: FakeEngine())

    response = client.delete("/api/database/tables/sample_table/indexes/idx_other_table_id")

    assert response.status_code == 404
    assert "not found on table" in response.json()["detail"]
    assert not any("DROP INDEX" in sql for sql, _ in captured)


def test_clone_table_copies_column_and_custom_dataset_metadata(monkeypatch):
    captured = []

    class FakeInspector:
        def has_table(self, table_name, schema=None):
            return schema == "vector" and table_name == "source_table"

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            captured.append((str(statement), params))

        def commit(self):
            captured.append(("COMMIT", None))

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(database, "inspect", lambda engine: FakeInspector())
    monkeypatch.setattr(database, "get_db_engine", lambda: FakeEngine())

    response = client.post(
        "/api/database/tables/source_table/clone",
        json={"new_name": "clone_table", "include_data": False},
    )

    assert response.status_code == 200
    assert any("INSERT INTO metadata.column_descriptions" in sql for sql, _ in captured)
    assert any("INSERT INTO metadata.custom_datasets" in sql for sql, _ in captured)


def test_truncate_table_updates_metadata_row_counts(monkeypatch):
    captured = []

    class FakeInspector:
        def has_table(self, table_name, schema=None):
            return table_name == "sample_table" and schema == "vector"

        def get_columns(self, table_name, schema=None):
            return [{"name": "id", "type": "INTEGER"}]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            captured.append((str(statement), params))

        def commit(self):
            captured.append(("COMMIT", None))

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(database, "inspect", lambda engine: FakeInspector())
    monkeypatch.setattr(database, "get_db_engine", lambda: FakeEngine())

    response = client.post("/api/database/tables/sample_table/truncate")

    assert response.status_code == 200
    table_description_updates = [
        (sql, params)
        for sql, params in captured
        if "UPDATE metadata.table_descriptions" in sql
    ]
    custom_updates = [
        (sql, params)
        for sql, params in captured
        if "UPDATE metadata.custom_datasets" in sql
    ]
    assert table_description_updates
    assert table_description_updates[0][1] == {"table_name": "sample_table"}
    assert custom_updates
    assert custom_updates[0][1] == {"table_name": "sample_table"}


def test_create_table_rejects_duplicate_columns(monkeypatch):
    class FakeInspector:
        def has_table(self, table_name, schema=None):
            return False

    class FailingEngine:
        def connect(self):
            raise AssertionError("SQL execution should not be reached")

    monkeypatch.setattr(database, "inspect", lambda engine: FakeInspector())
    monkeypatch.setattr(database, "get_db_engine", lambda: FailingEngine())

    response = client.post(
        "/api/database/tables/create",
        json={
            "table_name": "new_table",
            "columns": [
                {"name": "name", "data_type": "text"},
                {"name": "name", "data_type": "integer"},
            ],
        },
    )

    assert response.status_code == 400
    assert "Duplicate column" in response.json()["detail"]
