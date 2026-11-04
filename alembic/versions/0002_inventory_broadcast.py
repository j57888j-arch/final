"""Individual encrypted inventory resources and rich broadcast metadata.

Revision ID: 0002_inventory_broadcast
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_inventory_broadcast"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # 0001 in early distributions used metadata.create_all and can already include
    # these objects when a fresh database is installed with the newer source tree.
    if "inventory_items" not in tables:
        op.create_table(
            "inventory_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("service_id", sa.Integer(), sa.ForeignKey("services.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("resource_ciphertext", sa.Text(), nullable=False),
            sa.Column("resource_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("resource_mask", sa.String(length=120), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="available"),
            sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_by", sa.BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("service_id", "resource_fingerprint", name="uq_inventory_item_resource"),
        )
        op.create_index("ix_inventory_items_service_status", "inventory_items", ["service_id", "status"])
        op.create_index("ix_inventory_items_status", "inventory_items", ["status"])
        op.create_index("ix_inventory_items_order_id", "inventory_items", ["order_id"])

    if "broadcast_campaigns" in tables:
        columns = {column["name"] for column in inspector.get_columns("broadcast_campaigns")}
        if "source_chat_id" not in columns:
            op.add_column("broadcast_campaigns", sa.Column("source_chat_id", sa.BigInteger(), nullable=True))
        if "source_message_id" not in columns:
            op.add_column("broadcast_campaigns", sa.Column("source_message_id", sa.Integer(), nullable=True))
        if "button_text" not in columns:
            op.add_column("broadcast_campaigns", sa.Column("button_text", sa.String(length=64), nullable=True))
        if "button_url" not in columns:
            op.add_column("broadcast_campaigns", sa.Column("button_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "broadcast_campaigns" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("broadcast_campaigns")}
        for name in ("button_url", "button_text", "source_message_id", "source_chat_id"):
            if name in columns:
                op.drop_column("broadcast_campaigns", name)
    if "inventory_items" in inspector.get_table_names():
        op.drop_table("inventory_items")
