"""PostgreSQL-only audit and original-measurement protection for MVP tables.

This is an extra defense, not a substitute for a least-privilege DB account.
"""
from sqlalchemy import text

TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION steelflow_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is append-only; create a new event instead.', TG_TABLE_NAME;
END;
$$;
"""

RECEIPT_GUARD_SQL = """
CREATE OR REPLACE FUNCTION steelflow_receipt_weights_fixed() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.gross_kg IS DISTINCT FROM OLD.gross_kg OR
     NEW.tare_kg IS DISTINCT FROM OLD.tare_kg OR
     NEW.net_kg IS DISTINCT FROM OLD.net_kg OR
     NEW.weighbridge_ticket IS DISTINCT FROM OLD.weighbridge_ticket THEN
    RAISE EXCEPTION 'Original receipt weight and ticket are immutable.';
  END IF;
  RETURN NEW;
END;
$$;
"""
TRANSFER_GUARD_SQL = """
CREATE OR REPLACE FUNCTION steelflow_transfer_weights_fixed() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
 IF (OLD.dispatched_kg IS NOT NULL AND NEW.dispatched_kg IS DISTINCT FROM OLD.dispatched_kg) OR
    (OLD.received_kg IS NOT NULL AND NEW.received_kg IS DISTINCT FROM OLD.received_kg) OR
    (OLD.credited_kg IS NOT NULL AND NEW.credited_kg IS DISTINCT FROM OLD.credited_kg) THEN
   RAISE EXCEPTION 'Original transfer measurements are immutable.';
 END IF;
 RETURN NEW;
END;
$$;
"""

def install(engine):
    if engine.dialect.name != 'postgresql':
        return
    with engine.begin() as conn:
        conn.execute(text(TRIGGER_SQL))
        conn.execute(text(RECEIPT_GUARD_SQL))
        conn.execute(text(TRANSFER_GUARD_SQL))
        for table in ('receipt_inspections','transfer_measurements','inventory_events','audit_events','transit_adjustments'):
            name = 'sf_guard_'+table
            conn.execute(text(f'DROP TRIGGER IF EXISTS {name} ON {table}'))
            conn.execute(text(f'CREATE TRIGGER {name} BEFORE UPDATE OR DELETE ON {table} '
                              'FOR EACH ROW EXECUTE FUNCTION steelflow_append_only()'))
        for table,trigger,func in (
            ('inbound_receipts','sf_receipt_weight_guard','steelflow_receipt_weights_fixed'),
            ('transfers','sf_transfer_weight_guard','steelflow_transfer_weights_fixed'),
        ):
            conn.execute(text(f'DROP TRIGGER IF EXISTS {trigger} ON {table}'))
            conn.execute(text(f'CREATE TRIGGER {trigger} BEFORE UPDATE ON {table} '
                              f'FOR EACH ROW EXECUTE FUNCTION {func}()'))
