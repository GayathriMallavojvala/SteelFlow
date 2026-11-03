"""Implemented database model. Supersedes the earlier *proposal* SQL blueprint.

All quantities are Decimal-backed Numeric(18,3), stored in kilograms.
No successful business action is allowed outside an explicit database transaction.
"""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import String, Boolean, ForeignKey, DateTime, Numeric, Text, CheckConstraint, UniqueConstraint, Index, JSON
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

def uuid_str(): return str(uuid4())
def now(): return datetime.now(timezone.utc)

class Department(Base):
    __tablename__ = "departments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(160))

class User(Base):
    __tablename__ = "app_users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(30))
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("app_users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

class MaterialType(Base):
    __tablename__ = "material_types"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(30))

class Location(Base):
    __tablename__ = "storage_locations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"))
    kind: Mapped[str] = mapped_column(String(20))

class Route(Base):
    __tablename__ = "allowed_routes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    source_id: Mapped[str] = mapped_column(ForeignKey("storage_locations.id"))
    destination_id: Mapped[str] = mapped_column(ForeignKey("storage_locations.id"))
    __table_args__ = (UniqueConstraint("source_id", "destination_id"),)

class Receipt(Base):
    __tablename__ = "inbound_receipts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    receipt_no: Mapped[str] = mapped_column(String(40), unique=True)
    material_type_id: Mapped[str] = mapped_column(ForeignKey("material_types.id"))
    supplier: Mapped[str] = mapped_column(String(160))
    delivery_reference: Mapped[str] = mapped_column(String(120))
    vehicle_number: Mapped[str] = mapped_column(String(80))
    weighbridge_ticket: Mapped[str] = mapped_column(String(120), unique=True)
    gross_kg: Mapped[float] = mapped_column(Numeric(18,3))
    tare_kg: Mapped[float] = mapped_column(Numeric(18,3))
    net_kg: Mapped[float] = mapped_column(Numeric(18,3))
    target_location_id: Mapped[str] = mapped_column(ForeignKey("storage_locations.id"))
    status: Mapped[str] = mapped_column(String(25), default="AWAITING_INSPECTION")
    created_by: Mapped[str] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        CheckConstraint("gross_kg > tare_kg AND tare_kg >= 0 AND net_kg > 0", name="receipt_weight_valid"),
        CheckConstraint("net_kg = gross_kg - tare_kg", name="receipt_net_consistent"),
    )

class Inspection(Base):
    __tablename__ = "receipt_inspections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    receipt_id: Mapped[str] = mapped_column(ForeignKey("inbound_receipts.id"), index=True)
    decision: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    decided_by: Mapped[str] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Lot(Base):
    __tablename__ = "material_lots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    lot_no: Mapped[str] = mapped_column(String(40), unique=True)
    material_type_id: Mapped[str] = mapped_column(ForeignKey("material_types.id"))
    receipt_id: Mapped[str] = mapped_column(ForeignKey("inbound_receipts.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Stock(Base):
    __tablename__ = "stock_balances"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    lot_id: Mapped[str] = mapped_column(ForeignKey("material_lots.id"))
    location_id: Mapped[str] = mapped_column(ForeignKey("storage_locations.id"))
    on_hand_kg: Mapped[float] = mapped_column(Numeric(18,3), default=0)
    reserved_kg: Mapped[float] = mapped_column(Numeric(18,3), default=0)
    __table_args__ = (
        UniqueConstraint("lot_id", "location_id"),
        CheckConstraint("on_hand_kg >= 0 AND reserved_kg >= 0 AND reserved_kg <= on_hand_kg", name="stock_valid"),
    )

class Transfer(Base):
    __tablename__ = "transfers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    transfer_no: Mapped[str] = mapped_column(String(40), unique=True)
    lot_id: Mapped[str] = mapped_column(ForeignKey("material_lots.id"))
    source_id: Mapped[str] = mapped_column(ForeignKey("storage_locations.id"))
    destination_id: Mapped[str] = mapped_column(ForeignKey("storage_locations.id"))
    transit_id: Mapped[str] = mapped_column(ForeignKey("storage_locations.id"))
    reserved_kg: Mapped[float] = mapped_column(Numeric(18,3))
    dispatched_kg: Mapped[float | None] = mapped_column(Numeric(18,3))
    received_kg: Mapped[float | None] = mapped_column(Numeric(18,3))
    credited_kg: Mapped[float | None] = mapped_column(Numeric(18,3))
    status: Mapped[str] = mapped_column(String(35), default="RESERVED")
    created_by: Mapped[str] = mapped_column(ForeignKey("app_users.id"))
    dispatched_by: Mapped[str | None] = mapped_column(ForeignKey("app_users.id"))
    received_by: Mapped[str | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("reserved_kg > 0", name="transfer_reservation_valid"),)

class Measurement(Base):
    __tablename__ = "transfer_measurements"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    transfer_id: Mapped[str] = mapped_column(ForeignKey("transfers.id"))
    side: Mapped[str] = mapped_column(String(10))
    weight_kg: Mapped[float] = mapped_column(Numeric(18,3))
    evidence_reference: Mapped[str] = mapped_column(String(120))
    recorded_by: Mapped[str] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class LedgerEvent(Base):
    __tablename__ = "inventory_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    event_group: Mapped[str] = mapped_column(String(36))
    lot_id: Mapped[str] = mapped_column(ForeignKey("material_lots.id"))
    location_id: Mapped[str] = mapped_column(ForeignKey("storage_locations.id"))
    delta_kg: Mapped[float] = mapped_column(Numeric(18,3))
    action: Mapped[str] = mapped_column(String(30))
    reference_id: Mapped[str] = mapped_column(String(36))
    created_by: Mapped[str] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Discrepancy(Base):
    __tablename__ = "discrepancies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    transfer_id: Mapped[str] = mapped_column(ForeignKey("transfers.id"), unique=True)
    difference_kg: Mapped[float] = mapped_column(Numeric(18,3))
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    investigation_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Adjustment(Base):
    """Approved accounting-only clearance of a positive short-receipt balance.

    Does not assert that the material was physically lost; a controller must
    retain supporting evidence and an explanatory audit event.
    """
    __tablename__ = "transit_adjustments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    discrepancy_id: Mapped[str] = mapped_column(ForeignKey("discrepancies.id"), unique=True)
    transfer_id: Mapped[str] = mapped_column(ForeignKey("transfers.id"), index=True)
    lot_id: Mapped[str] = mapped_column(ForeignKey("material_lots.id"), index=True)
    amount_kg: Mapped[float] = mapped_column(Numeric(18,3))
    category: Mapped[str] = mapped_column(String(45), default="APPROVED_TRANSIT_ADJUSTMENT")
    reason: Mapped[str] = mapped_column(Text)
    evidence_reference: Mapped[str] = mapped_column(String(120))
    approved_by: Mapped[str] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (CheckConstraint("amount_kg > 0", name="adjustment_positive"),)

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    actor_id: Mapped[str] = mapped_column(ForeignKey("app_users.id"))
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(40))
    details: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

Index("ix_events_lot_location", LedgerEvent.lot_id, LedgerEvent.location_id)
Index("ix_transfers_status", Transfer.status)
