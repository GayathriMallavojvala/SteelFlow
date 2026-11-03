"""Read-only material reconciliation from persisted inventory events and stock.

All mass quantities are Decimal kilograms. The accounting equation here is
received material = current stock across locations + approved adjustments.
This verifies records are self-consistent, NOT that instruments are accurate.
"""
from collections import defaultdict
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Lot, Receipt, Stock, LedgerEvent, Adjustment, Transfer, Location, Discrepancy

ZERO = Decimal('0.000')

def d(v):
    return Decimal(str(v or '0'))

def fmt(v):
    return str(d(v).quantize(Decimal('0.001')))


def lot_reconciliation(db:Session, lot:Lot):
    """Compare an immutable running ledger to current on-hand stock, per location.

    There is no default tolerance here: stock ledger is a precise bookkeeping
    check. Measurement tolerance is separate engineering configuration.
    """
    events=db.scalars(select(LedgerEvent).where(LedgerEvent.lot_id==lot.id)).all()
    stock=db.scalars(select(Stock).where(Stock.lot_id==lot.id)).all()
    adjustments=db.scalars(select(Adjustment).where(Adjustment.lot_id==lot.id)).all()
    expected=defaultdict(lambda:ZERO)
    for e in events: expected[e.location_id] += d(e.delta_kg)
    actual={x.location_id:d(x.on_hand_kg) for x in stock}
    details=[]
    for loc_id in sorted(set(expected)|set(actual)):
        location=db.get(Location,loc_id)
        ledger=expected[loc_id]; on_hand=actual.get(loc_id,ZERO)
        details.append({'location':location.name if location else loc_id,
                        'location_code':location.code if location else 'UNKNOWN',
                        'ledger_kg':fmt(ledger),'on_hand_kg':fmt(on_hand),
                        'difference_kg':fmt(on_hand-ledger),'matches':on_hand==ledger})
    opening=d(db.get(Receipt,lot.receipt_id).net_kg)
    current=sum(actual.values(),ZERO)
    adjusted=sum((d(x.amount_kg) for x in adjustments),ZERO)
    signed_changes=sum((d(x.delta_kg) for x in events),ZERO)
    processed=sum((-d(x.delta_kg) for x in events if x.action=='PROCESS_CONSUME'),ZERO)
    consistent=all(x['matches'] for x in details) and current+adjusted+processed==opening and signed_changes==current
    return {'lot_id':lot.id,'lot_no':lot.lot_no,'original_received_kg':fmt(opening),
            'current_stock_kg':fmt(current),'approved_adjustments_kg':fmt(adjusted),
            'consumed_in_production_kg':fmt(processed),
            'unexplained_accounting_difference_kg':fmt(opening-current-adjusted-processed),
            'ledger_matches_stock':all(x['matches'] for x in details),
            'status':'RECORDS_CONSISTENT' if consistent else 'RECORDS_REQUIRE_REVIEW',
            'locations':details,
            'interpretation':'A consistent ledger does not prove weighing accuracy or establish physical root cause.'}


def transfer_reconciliation(t:Transfer):
    dispatch=d(t.dispatched_kg) if t.dispatched_kg is not None else None
    receipt=d(t.received_kg) if t.received_kg is not None else None
    if dispatch is None:
        stage='NOT_DISPATCHED'; difference=None
        message='Reserved material has not been dispatched.'
    elif receipt is None:
        stage='AWAITING_RECEIPT'; difference=None
        message='Departure recorded; independently measured receipt is pending.'
    else:
        difference=dispatch-receipt
        if difference>0:
            stage='SHORT_RECEIPT';message='Less material was measured at receipt than at dispatch. Cause unverified.'
        elif difference<0:
            stage='OVER_RECEIPT';message='More material was measured at receipt than at dispatch. Excess not automatically credited.'
        else:
            stage='MATCHED';message='Recorded dispatch and receipt weights match.'
    return {'transfer_id':t.id,'transfer_no':t.transfer_no,
            'reserved_kg':fmt(t.reserved_kg),'dispatched_kg':fmt(dispatch) if dispatch is not None else None,
            'received_kg':fmt(receipt) if receipt is not None else None,
            'difference_kg':fmt(difference) if difference is not None else None,
            'stage':stage,'message':message}


def overview(db:Session):
    lots=db.scalars(select(Lot).order_by(Lot.created_at.desc())).all()
    transfers=db.scalars(select(Transfer).order_by(Transfer.created_at.desc())).all()
    checks=[lot_reconciliation(db,lot) for lot in lots]
    movements=[transfer_reconciliation(t) for t in transfers]
    all_cases=db.scalars(select(Discrepancy)).all()
    case_status={case.transfer_id:case.status for case in all_cases}
    for movement in movements:
        movement['case_status']=case_status.get(movement['transfer_id'])
    unresolved=[case for case in all_cases if case.status in ('OPEN','IN_REVIEW')]
    return {'summary':{
            'lots_checked':len(checks),
            'unresolved_discrepancies':len(unresolved),
            'lots_consistent':sum(x['status']=='RECORDS_CONSISTENT' for x in checks),
            'lots_require_review':sum(x['status']!='RECORDS_CONSISTENT' for x in checks),
            'short_receipts':sum(x['stage']=='SHORT_RECEIPT' for x in movements),
            'over_receipts':sum(x['stage']=='OVER_RECEIPT' for x in movements),
            'pending_receipts':sum(x['stage']=='AWAITING_RECEIPT' for x in movements),
            'approved_adjustments_kg':fmt(sum((d(x['approved_adjustments_kg']) for x in checks),ZERO))},
            'lots':checks,'transfers':movements,
            'notice':'These checks validate recorded quantities and ledger consistency, not physical root causes.'}
