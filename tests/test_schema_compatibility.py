import os
import tempfile
import pytest
from pathlib import Path
from alembic.config import Config as AlembicConfig
from alembic import command
from sqlalchemy import create_engine, inspect
from app import create_app
from app.config import Config

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_migrations_upgrade_and_schema():
    """Verify that all migrations apply cleanly on a fresh database and produce expected schema."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        tmp_path = tmp.name

    try:
        db_url = f"sqlite:///{Path(tmp_path).as_posix()}"

        class TestMigrateConfig(Config):
            SQLALCHEMY_DATABASE_URI = db_url
            TESTING = True
            WTF_CSRF_ENABLED = False

        app = create_app(TestMigrateConfig)

        alembic_cfg = AlembicConfig(str(PROJECT_ROOT / "migrations" / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)

        with app.app_context():
            command.upgrade(alembic_cfg, "head")

        engine = create_engine(db_url)
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        # Check critical tables exist
        expected_tables = [
            "users", "customers", "lots", "operating_costs",
            "cash_advance_monthly", "cash_advance_transactions",
            "cash_advance_bill_media", "audit_logs", "alembic_version"
        ]
        for tbl in expected_tables:
            assert tbl in tables, f"Expected table '{tbl}' not found in migrated database: {tables}"

        # Check cash_advance_monthly columns
        cam_cols = {c["name"] for c in inspector.get_columns("cash_advance_monthly")}
        assert "is_locked" in cam_cols
        assert "locked_at" in cam_cols
        assert "locked_by" in cam_cols

        # Check cash_advance_transactions columns
        cat_cols = {c["name"] for c in inspector.get_columns("cash_advance_transactions")}
        assert "external_id" in cat_cols
        assert "sync_status" in cat_cols
        assert "sync_hash" in cat_cols
        assert "is_deleted" in cat_cols

        # Check audit_logs columns
        al_cols = {c["name"] for c in inspector.get_columns("audit_logs")}
        assert "actor" in al_cols
        assert "before_state" in al_cols
        assert "after_state" in al_cols
        assert "reason" in al_cols
        assert "request_id" in al_cols

        # Check lots & operating_costs soft delete columns
        lot_cols = {c["name"] for c in inspector.get_columns("lots")}
        assert "is_deleted" in lot_cols
        cost_cols = {c["name"] for c in inspector.get_columns("operating_costs")}
        assert "is_deleted" in cost_cols

        # Revision 0003: bill media must be explicitly linked rather than
        # inferred from user names or free text.
        bill_cols = {c["name"] for c in inspector.get_columns("cash_advance_bill_media")}
        assert {"transaction_id", "operating_cost_id", "lot_id", "uploaded_by"} <= bill_cols
        bill_fk_columns = {fk["constrained_columns"][0] for fk in inspector.get_foreign_keys("cash_advance_bill_media")}
        assert {"transaction_id", "operating_cost_id", "lot_id", "uploaded_by"} <= bill_fk_columns

        revenue_cols = {c["name"] for c in inspector.get_columns("revenue_items")}
        assert {"is_deleted", "deleted_at", "deleted_by"} <= revenue_cols
        cost_cols = {c["name"] for c in inspector.get_columns("operating_costs")}
        assert {"source_sheet", "source_row", "source_payload"} <= cost_cols

        engine.dispose()
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
