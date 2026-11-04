from sqlalchemy import create_engine

from app.database.base import Base
from app.database import models  # noqa: F401


def test_schema_can_be_created_on_sqlite(tmp_path):
    db_path = tmp_path / "schema.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    inspector = __import__("sqlalchemy").inspect(engine)
    tables = set(inspector.get_table_names())
    assert "users" in tables
    assert "orders" in tables
    assert "ledger_entries" in tables
    assert "outbox_events" in tables
    assert "admin_user_roles" in tables
    assert "inventory_items" in tables
    engine.dispose()
