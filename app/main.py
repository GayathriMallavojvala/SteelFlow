"""SteelFlow API MVP — yard receipt, inspection, stock and transfer to SMS.

NOT production-certified: integration with plant control systems and real-world
material controls requires independent verification and a security assessment.
"""
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from typing import Literal
from fastapi import Depends, FastAPI, HTTPException, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, update, func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .db import Base, new_engine, make_session_factory
from .models import (User, AuthSession, MaterialType, Location, Route, Receipt, Inspection,
                     Lot, Stock, Transfer, Measurement, LedgerEvent, Discrepancy, Adjustment, AuditEvent, now)
from .security import verify_password, new_token, token_hash, token_expiry
from .reconciliation import overview as reconciliation_overview, lot_reconciliation
from .manufacturing import routes as manufacturing_routes

KG = Decimal('0.001')

def money(v):
    return f'{Decimal(v).quantize(KG):.3f}'

def ref(prefix: str):
    # UUID-derived unique, non-sequential opaque ref; operator never types it.
    return f'{prefix}-{uuid4().hex[:12].upper()}'

def fail(message: str, status: int = 400):
    raise HTTPException(status_code=status, detail=message)

def receipt_dict(r: Receipt, db: Session):
    m = db.get(MaterialType, r.material_type_id)
    loc = db.get(Location, r.target_location_id)
    return {'id':r.id, 'receipt_no':r.receipt_no, 'material':m.name, 'material_code':m.code,
            'supplier':r.supplier, 'delivery_reference':r.delivery_reference,
            'vehicle_number':r.vehicle_number, 'ticket':r.weighbridge_ticket,
            'gross_kg':money(r.gross_kg), 'tare_kg':money(r.tare_kg), 'net_kg':money(r.net_kg),
            'location':loc.name, 'status':r.status, 'created_at':r.created_at.isoformat()}

def transfer_dict(t: Transfer, db:Session):
    lot = db.get(Lot, t.lot_id)
    src = db.get(Location, t.source_id)
    dst = db.get(Location, t.destination_id)
    measures = db.scalars(select(Measurement).where(Measurement.transfer_id==t.id)).all()
    dispatch_measure = next((m for m in measures if m.side=='DISPATCH'), None)
    receipt_measure = next((m for m in measures if m.side=='RECEIPT'), None)
    diff = None if t.received_kg is None else money(Decimal(t.dispatched_kg)-Decimal(t.received_kg))
    return {'id':t.id,'transfer_no':t.transfer_no, 'lot_no':lot.lot_no,
            'source':src.name, 'destination':dst.name, 'reserved_kg':money(t.reserved_kg),
            'dispatched_kg':money(t.dispatched_kg) if t.dispatched_kg is not None else None,
            'received_kg':money(t.received_kg) if t.received_kg is not None else None,
            'credited_kg':money(t.credited_kg) if t.credited_kg is not None else None,
            'difference_kg':diff, 'status':t.status, 'created_at':t.created_at.isoformat(),
            'dispatch_reference':dispatch_measure.evidence_reference if dispatch_measure else None,
            'receipt_reference':receipt_measure.evidence_reference if receipt_measure else None,
            'dispatched_at':t.dispatched_at.isoformat() if t.dispatched_at else None,
            'received_at':t.received_at.isoformat() if t.received_at else None}

def audit(db, user, obj, action, extra=None):
    db.add(AuditEvent(actor_id=user.id, entity_type=type(obj).__name__, entity_id=obj.id,
                      action=action, details=extra or {}))

def add_stock(db: Session, lot_id: str, location_id: str, amount: Decimal):
    """Atomic upsert prevents competing dispatches from creating duplicate stock rows."""
    if amount <= 0:
        return
    dialect = db.get_bind().dialect.name
    if dialect == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == 'sqlite':
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise RuntimeError(f'Unsupported database for atomic stock upsert: {dialect}')
    stmt=insert(Stock).values(lot_id=lot_id,location_id=location_id,
                              on_hand_kg=amount,reserved_kg=Decimal(0))
    stmt=stmt.on_conflict_do_update(index_elements=['lot_id','location_id'],
                                    set_={'on_hand_kg':Stock.on_hand_kg+amount})
    db.execute(stmt)

def event(db, user, lot, loc, amount, action, reference, group):
    db.add(LedgerEvent(event_group=group, lot_id=lot, location_id=loc,
                       delta_kg=amount, action=action, reference_id=reference, created_by=user.id))

class LoginIn(BaseModel):
    username: str
    password: str

class ReceiveIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    material_code: str
    supplier: str = Field(min_length=2,max_length=160)
    delivery_reference: str = Field(min_length=1,max_length=120)
    vehicle_number: str = Field(min_length=4,max_length=80)
    weighbridge_ticket: str = Field(min_length=2,max_length=120)
    gross_kg: Decimal = Field(gt=0, max_digits=18, decimal_places=3)
    tare_kg: Decimal = Field(ge=0, max_digits=18, decimal_places=3)
    location_code: str = 'YARD-A'

class ReviewIn(BaseModel):
    decision: Literal['RELEASED','HELD','REJECTED']
    reason: str = Field(min_length=3,max_length=1000)

class ReserveIn(BaseModel):
    lot_id: str
    quantity_kg: Decimal = Field(gt=0, max_digits=18, decimal_places=3)
    source_code: str = 'YARD-A'
    destination_code: str = 'SMS-RECEIVING'

class DispatchIn(BaseModel):
    evidence_reference: str = Field(min_length=2,max_length=120)
    measured_kg: Decimal = Field(gt=0, max_digits=18, decimal_places=3)


class ConfirmIn(BaseModel):
    received_kg: Decimal = Field(ge=0, max_digits=18, decimal_places=3)
    evidence_reference: str = Field(min_length=2,max_length=120)

class InvestigateIn(BaseModel):
    note: str = Field(min_length=10,max_length=3000)

class CloseShortageIn(BaseModel):
    reason: str = Field(min_length=20,max_length=3000)
    evidence_reference: str = Field(min_length=4,max_length=120)
    confirm_accounting_adjustment: Literal[True]


def create_app(database_url: str|None=None):
    app = FastAPI(title='SteelFlow — Material Operations API', version='1.0.0',
                  description='Training MVP. Batch-linked material transfers, measured discrepancies, and role-protected workflows. API values in kilograms.')
    engine = new_engine(database_url)
    Base.metadata.create_all(engine)
    from .pg_guards import install as install_pg_guards
    install_pg_guards(engine)
    SessionLocal = make_session_factory(engine)
    app.state.db_engine = engine
    app.state.SessionLocal = SessionLocal

    def db_dep():
        with SessionLocal() as session:
            yield session

    def auth_user(authorization: str|None=Header(default=None), db:Session=Depends(db_dep)):
        if not authorization or not authorization.startswith('Bearer '):
            fail('Please sign in first.',401)
        token = authorization[7:].strip()
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash==token_hash(token), AuthSession.revoked==False))
        if not session:
            fail('Your session has ended. Sign in again.',401)
        until = session.expires_at
        if until.tzinfo is None: until=until.replace(tzinfo=timezone.utc)
        if until <= now(): fail('Session expired. Sign in again.',401)
        user = db.get(User, session.user_id)
        if not user or not user.active: fail('Your account is unavailable.',401)
        return user

    def restrict(*roles):
        def check(user=Depends(auth_user)):
            if user.role not in roles:
                fail('Your role cannot perform this action.',403)
            return user
        return check

    @app.get('/api/health')
    def health():return {'status':'ok','database':'configured','mode':'training-mvp'}

    @app.post('/api/auth/login')
    def login(body:LoginIn, db:Session=Depends(db_dep)):
        user=db.scalar(select(User).where(User.username==body.username,User.active==True))
        if not user or not verify_password(body.password,user.password_hash):
            fail('Incorrect username or password.',401)
        token=new_token()
        db.add(AuthSession(user_id=user.id,token_hash=token_hash(token),expires_at=token_expiry()))
        db.commit()
        return {'access_token':token,'token_type':'bearer','display_name':user.display_name,'role':user.role}

    @app.get('/api/me')
    def me(user=Depends(auth_user)):
        return {'username':user.username,'name':user.display_name,'role':user.role}

    @app.get('/api/config')
    def config(db:Session=Depends(db_dep), user=Depends(auth_user)):
        return {'materials':[{'code':m.code,'name':m.name} for m in db.scalars(select(MaterialType).order_by(MaterialType.name))],
                'locations':[{'code':l.code,'name':l.name,'kind':l.kind} for l in db.scalars(select(Location).order_by(Location.name))]}

    @app.post('/api/receipts',status_code=201)
    def receive(body:ReceiveIn, db:Session=Depends(db_dep), user=Depends(restrict('YARD_OPERATOR'))):
        if body.gross_kg <= body.tare_kg:
            fail('Gross weight must be greater than the empty-vehicle (tare) weight.')
        mat=db.scalar(select(MaterialType).where(MaterialType.code==body.material_code))
        loc=db.scalar(select(Location).where(Location.code==body.location_code,Location.kind=='YARD'))
        if not mat or not loc: fail('Choose a valid material and yard storage location.')
        if db.scalar(select(Receipt.id).where(Receipt.weighbridge_ticket==body.weighbridge_ticket)):
            fail('This weighbridge ticket has already been recorded.',409)
        r=Receipt(receipt_no=ref('REC'),material_type_id=mat.id,supplier=body.supplier,
                  delivery_reference=body.delivery_reference,vehicle_number=body.vehicle_number,
                  weighbridge_ticket=body.weighbridge_ticket,gross_kg=body.gross_kg,
                  tare_kg=body.tare_kg,net_kg=body.gross_kg-body.tare_kg,
                  target_location_id=loc.id,status='AWAITING_INSPECTION',created_by=user.id)
        db.add(r); db.flush()
        audit(db,user,r,'RECEIPT_SUBMITTED',{'net_kg':money(r.net_kg),'ticket':r.weighbridge_ticket})
        try: db.commit()
        except IntegrityError:
            db.rollback(); fail('Receipt or ticket was already recorded. Check the ticket number.',409)
        return receipt_dict(r,db)

    @app.get('/api/receipts')
    def list_receipts(db:Session=Depends(db_dep),user=Depends(auth_user)):
        rows=db.scalars(select(Receipt).order_by(Receipt.created_at.desc()).limit(300)).all()
        return [receipt_dict(r,db) for r in rows]

    @app.post('/api/receipts/{receipt_id}/review')
    def review(receipt_id:str, body:ReviewIn,db:Session=Depends(db_dep),user=Depends(restrict('YARD_SUPERVISOR'))):
        # State compare-and-swap prevents a second release on concurrent requests.
        r=db.get(Receipt,receipt_id)
        if not r: fail('Receipt not found.',404)
        if r.status not in ('AWAITING_INSPECTION','HELD'):
            fail('This receipt has already received its final decision.',409)
        affected=db.execute(update(Receipt).where(Receipt.id==receipt_id,Receipt.status==r.status).values(status=body.decision)).rowcount
        if affected!=1: db.rollback();fail('Receipt was changed by another supervisor. Refresh and retry.',409)
        decision=Inspection(receipt_id=r.id,decision=body.decision,reason=body.reason,decided_by=user.id)
        db.add(decision)
        if body.decision=='RELEASED':
            lot=Lot(lot_no=ref('LOT'),material_type_id=r.material_type_id,receipt_id=r.id)
            db.add(lot); db.flush()
            db.add(Stock(lot_id=lot.id,location_id=r.target_location_id,on_hand_kg=r.net_kg,reserved_kg=Decimal(0)))
            event(db,user,lot.id,r.target_location_id,r.net_kg,'RECEIPT_RELEASE',r.id,str(uuid4()))
        audit(db,user,r,'INSPECTION_'+body.decision,{'reason':body.reason})
        try: db.commit()
        except IntegrityError:
            db.rollback();fail('This receipt has already been processed.',409)
        db.refresh(r)
        return receipt_dict(r,db)

    @app.get('/api/inventory')
    def inventory(db:Session=Depends(db_dep),user=Depends(auth_user)):
        rows=db.execute(select(Stock,Lot,Location,MaterialType)
            .join(Lot,Stock.lot_id==Lot.id).join(Location,Stock.location_id==Location.id)
            .join(MaterialType,Lot.material_type_id==MaterialType.id)
            .order_by(Lot.created_at.desc())).all()
        return [{'lot_id':l.id,'lot_no':l.lot_no,'material':mat.name,'material_code':mat.code,
                 'location':loc.name,'location_code':loc.code,'location_kind':loc.kind,
                 'on_hand_kg':money(s.on_hand_kg),'reserved_kg':money(s.reserved_kg),
                 'available_kg':money(Decimal(s.on_hand_kg)-Decimal(s.reserved_kg))}
                for s,l,loc,mat in rows]

    @app.post('/api/transfers',status_code=201)
    def reserve(body:ReserveIn,db:Session=Depends(db_dep),user=Depends(restrict('YARD_OPERATOR'))):
        lot=db.get(Lot,body.lot_id)
        src=db.scalar(select(Location).where(Location.code==body.source_code))
        dst=db.scalar(select(Location).where(Location.code==body.destination_code))
        transit=db.scalar(select(Location).where(Location.code=='IN-TRANSIT'))
        if not lot or not src or not dst or not transit: fail('Choose a valid material lot and route.')
        if not db.scalar(select(Route.id).where(Route.source_id==src.id,Route.destination_id==dst.id)):
            fail('This destination is not an approved transfer route.')
        result=db.execute(update(Stock).where(Stock.lot_id==lot.id,Stock.location_id==src.id,
                    Stock.on_hand_kg-Stock.reserved_kg>=body.quantity_kg)
                    .values(reserved_kg=Stock.reserved_kg+body.quantity_kg))
        if result.rowcount!=1:
            db.rollback();fail('Not enough available stock. Check the quantity and try again.',409)
        tr=Transfer(transfer_no=ref('TRF'),lot_id=lot.id,source_id=src.id,destination_id=dst.id,
                    transit_id=transit.id,reserved_kg=body.quantity_kg,status='RESERVED',created_by=user.id)
        db.add(tr);db.flush()
        audit(db,user,tr,'TRANSFER_RESERVED',{'quantity_kg':money(body.quantity_kg)})
        db.commit()
        return transfer_dict(tr,db)

    @app.get('/api/lots/{lot_id}/history')
    def lot_history(lot_id:str, db:Session=Depends(db_dep), user=Depends(auth_user)):
        """Read-only trace for the current Yard -> Melting pilot.

        Every timeline entry comes from persisted operational records, not
        inferred process losses or guessed timestamps.
        """
        lot=db.get(Lot,lot_id)
        if not lot: fail('Material lot not found.',404)
        r=db.get(Receipt,lot.receipt_id)
        mat=db.get(MaterialType,lot.material_type_id)
        stocks=db.scalars(select(Stock).where(Stock.lot_id==lot.id)).all()
        transfers=db.scalars(select(Transfer).where(Transfer.lot_id==lot.id).order_by(Transfer.created_at)).all()
        inspections=db.scalars(select(Inspection).where(Inspection.receipt_id==r.id).order_by(Inspection.created_at)).all()
        timeline=[{'time':r.created_at.isoformat(),'event':'Delivery recorded',
                   'detail':f'{money(r.net_kg)} kg recorded against ticket {r.weighbridge_ticket}',
                   'reference':r.receipt_no}]
        for inspection in inspections:
            timeline.append({'time':inspection.created_at.isoformat(),
                             'event':{'RELEASED':'Material approved','HELD':'Material held','REJECTED':'Material rejected'}.get(inspection.decision,inspection.decision),
                             'detail':inspection.reason,'reference':r.receipt_no})
        adjustments=db.scalars(select(Adjustment).where(Adjustment.lot_id==lot.id).order_by(Adjustment.created_at)).all()
        for adjustment in adjustments:
            timeline.append({'time':adjustment.created_at.isoformat(),
                             'event':'Approved accounting adjustment',
                             'detail':f'{money(adjustment.amount_kg)} kg removed from transit accounting under {adjustment.evidence_reference}; this does not prove physical loss',
                             'reference':adjustment.evidence_reference})
        for t in transfers:
            timeline.append({'time':t.created_at.isoformat(),'event':'Material reserved for transfer',
                             'detail':f'{money(t.reserved_kg)} kg reserved for {db.get(Location,t.destination_id).name}',
                             'reference':t.transfer_no})
            if t.dispatched_at:
                timeline.append({'time':t.dispatched_at.isoformat(),'event':'Material dispatched',
                                 'detail':f'{money(t.dispatched_kg)} kg recorded leaving {db.get(Location,t.source_id).name}',
                                 'reference':t.transfer_no})
            if t.received_at:
                diff=Decimal(t.dispatched_kg)-Decimal(t.received_kg)
                label='Receipt recorded — review needed' if diff else 'Receipt recorded — matched'
                timeline.append({'time':t.received_at.isoformat(),'event':label,
                                 'detail':f'{money(t.received_kg)} kg recorded at {db.get(Location,t.destination_id).name}; difference {money(diff)} kg',
                                 'reference':t.transfer_no})
        return {'lot_id':lot.id,'lot_no':lot.lot_no,'material':mat.name,
                'supplier':r.supplier,'origin_receipt':r.receipt_no,'origin_weight_kg':money(r.net_kg),
                'stocks':[{'location':db.get(Location,x.location_id).name,
                           'on_hand_kg':money(x.on_hand_kg),'reserved_kg':money(x.reserved_kg)} for x in stocks],
                'transfers':[transfer_dict(t,db) for t in transfers],
                'timeline':sorted(timeline,key=lambda x:x['time'],reverse=True)}

    @app.get('/api/transfers')
    def list_transfers(db:Session=Depends(db_dep),user=Depends(auth_user)):
        ts=db.scalars(select(Transfer).order_by(Transfer.created_at.desc()).limit(300)).all()
        return [transfer_dict(t,db) for t in ts]

    @app.post('/api/transfers/{transfer_id}/dispatch')
    def dispatch(transfer_id:str,body:DispatchIn,db:Session=Depends(db_dep),user=Depends(restrict('YARD_OPERATOR'))):
        tr=db.get(Transfer,transfer_id)
        if not tr:fail('Transfer not found.',404)
        measured=body.measured_kg
        # The weighing ticket must not claim more material than was reserved.
        # Material not loaded stays in yard and becomes available again.
        if measured > Decimal(tr.reserved_kg):
            fail('Measured dispatch cannot exceed the reserved quantity. Update the reservation before dispatch.')
        changed=db.execute(update(Transfer).where(Transfer.id==tr.id,Transfer.status=='RESERVED')
                .values(status='DISPATCHED',dispatched_kg=measured,dispatched_by=user.id,dispatched_at=now())).rowcount
        if changed!=1:db.rollback();fail('This transfer cannot be dispatched again.',409)
        stock=db.execute(update(Stock).where(Stock.lot_id==tr.lot_id,Stock.location_id==tr.source_id,
                    Stock.on_hand_kg>=tr.reserved_kg,Stock.reserved_kg>=tr.reserved_kg)
                    .values(on_hand_kg=Stock.on_hand_kg-measured,reserved_kg=Stock.reserved_kg-tr.reserved_kg)).rowcount
        if stock!=1:db.rollback();fail('The reserved stock is no longer available.',409)
        add_stock(db,tr.lot_id,tr.transit_id,measured)
        group=str(uuid4())
        event(db,user,tr.lot_id,tr.source_id,-measured,'TRANSFER_DISPATCH',tr.id,group)
        event(db,user,tr.lot_id,tr.transit_id,measured,'TRANSFER_DISPATCH',tr.id,group)
        db.add(Measurement(transfer_id=tr.id,side='DISPATCH',weight_kg=measured,
                           evidence_reference=body.evidence_reference,recorded_by=user.id))
        audit(db,user,tr,'TRANSFER_DISPATCHED',{'measured_kg':money(measured),
              'reserved_kg':money(tr.reserved_kg),'reservation_released_kg':money(Decimal(tr.reserved_kg)-measured)})
        db.commit();db.refresh(tr)
        return transfer_dict(tr,db)

    @app.post('/api/transfers/{transfer_id}/receive')
    def acknowledge(transfer_id:str,body:ConfirmIn,db:Session=Depends(db_dep),user=Depends(restrict('SMS_OPERATOR'))):
        tr=db.get(Transfer,transfer_id)
        if not tr:fail('Transfer not found.',404)
        if tr.status!='DISPATCHED':fail('This transfer is not awaiting receipt.',409)
        credited=min(body.received_kg, Decimal(tr.dispatched_kg))
        status='RECEIVED_BALANCED' if body.received_kg==Decimal(tr.dispatched_kg) else 'RECEIVED_WITH_DIFFERENCE'
        affected=db.execute(update(Transfer).where(Transfer.id==tr.id,Transfer.status=='DISPATCHED')
                    .values(received_kg=body.received_kg,credited_kg=credited,status=status,
                            received_by=user.id,received_at=now())).rowcount
        if affected!=1:db.rollback();fail('Another operator already confirmed this receipt.',409)
        if credited>0:
            moved=db.execute(update(Stock).where(Stock.lot_id==tr.lot_id,Stock.location_id==tr.transit_id,
                                   Stock.on_hand_kg>=credited)
                           .values(on_hand_kg=Stock.on_hand_kg-credited)).rowcount
            if moved!=1:db.rollback();fail('Transit stock was inconsistent. Ask a supervisor to investigate.',409)
            add_stock(db,tr.lot_id,tr.destination_id,credited)
            group=str(uuid4())
            event(db,user,tr.lot_id,tr.transit_id,-credited,'TRANSFER_RECEIPT',tr.id,group)
            event(db,user,tr.lot_id,tr.destination_id,credited,'TRANSFER_RECEIPT',tr.id,group)
        db.add(Measurement(transfer_id=tr.id,side='RECEIPT',weight_kg=body.received_kg,
                           evidence_reference=body.evidence_reference,recorded_by=user.id))
        if status=='RECEIVED_WITH_DIFFERENCE':
            db.add(Discrepancy(transfer_id=tr.id,difference_kg=Decimal(tr.dispatched_kg)-body.received_kg))
        audit(db,user,tr,'TRANSFER_RECEIVED',{'measured_kg':money(body.received_kg),
                                              'credited_kg':money(credited),'status':status})
        db.commit();db.refresh(tr)
        return transfer_dict(tr,db)

    @app.get('/api/discrepancies')
    def discrepancies(db:Session=Depends(db_dep),user=Depends(auth_user)):
        rows=db.scalars(select(Discrepancy).order_by(Discrepancy.created_at.desc())).all()
        return [{'id':d.id,'transfer_id':d.transfer_id,'difference_kg':money(d.difference_kg),
                 'status':d.status,'note':d.investigation_note,
                 'transfer_no':db.get(Transfer,d.transfer_id).transfer_no} for d in rows]

    @app.post('/api/discrepancies/{discrepancy_id}/investigate')
    def investigate(discrepancy_id:str,body:InvestigateIn,db:Session=Depends(db_dep),user=Depends(restrict('CONTROLLER'))):
        d=db.get(Discrepancy,discrepancy_id)
        if not d:fail('Investigation not found.',404)
        if d.status!='OPEN':fail('This discrepancy already has an investigation note.',409)
        changed=db.execute(update(Discrepancy).where(Discrepancy.id==d.id,Discrepancy.status=='OPEN')
                           .values(status='IN_REVIEW',investigation_note=body.note,reviewed_by=user.id)).rowcount
        if changed!=1:db.rollback();fail('This investigation has already been started.',409)
        audit(db,user,d,'INVESTIGATION_STARTED',{'note':body.note})
        db.commit()
        return {'status':'IN_REVIEW','message':'Investigation saved. This does not change material balances.'}

    @app.post('/api/discrepancies/{discrepancy_id}/close-shortage')
    def close_shortage(discrepancy_id:str,body:CloseShortageIn,db:Session=Depends(db_dep),user=Depends(restrict('CONTROLLER'))):
        # Deliberately only permits *short* receipts. Over-receipt discrepancies
        # require a separate correction/verification workflow, not invented stock.
        discrepancy=db.get(Discrepancy,discrepancy_id)
        if not discrepancy:fail('Discrepancy not found.',404)
        tr=db.get(Transfer,discrepancy.transfer_id)
        if discrepancy.status!='IN_REVIEW':
            fail('Start and document an investigation before approving an adjustment.',409)
        difference=Decimal(discrepancy.difference_kg)
        if difference<=0 or tr.status!='RECEIVED_WITH_DIFFERENCE':
            fail('Only confirmed short-receipt records can use this accounting adjustment.',409)
        # Compare-and-swap guards duplicate approval by competing requests.
        claim=db.execute(update(Discrepancy).where(Discrepancy.id==discrepancy_id,Discrepancy.status=='IN_REVIEW')
                    .values(status='CLOSED_ADJUSTED')).rowcount
        if claim!=1:
            db.rollback();fail('This discrepancy has already changed. Refresh and retry.',409)
        deducted=db.execute(update(Stock).where(Stock.lot_id==tr.lot_id,Stock.location_id==tr.transit_id,
                                   Stock.on_hand_kg>=difference)
                           .values(on_hand_kg=Stock.on_hand_kg-difference)).rowcount
        if deducted!=1:
            db.rollback();fail('Transit balance is inconsistent. No adjustment was applied.',409)
        adjustment=Adjustment(discrepancy_id=discrepancy.id,transfer_id=tr.id,lot_id=tr.lot_id,
                             amount_kg=difference,reason=body.reason,
                             evidence_reference=body.evidence_reference,approved_by=user.id)
        db.add(adjustment);db.flush()
        event(db,user,tr.lot_id,tr.transit_id,-difference,'APPROVED_TRANSIT_ADJUSTMENT',adjustment.id,str(uuid4()))
        audit(db,user,discrepancy,'TRANSIT_ADJUSTMENT_APPROVED',{
            'amount_kg':money(difference),'reason':body.reason,'evidence_reference':body.evidence_reference,
            'not_proof_of_physical_loss':True})
        db.commit()
        return {'status':'CLOSED_ADJUSTED','adjusted_kg':money(difference),
                'message':'Approved accounting adjustment recorded. This is not proof of physical loss.'}

    @app.get('/api/reconciliation/overview')
    def reconciliation_report(db:Session=Depends(db_dep),user=Depends(restrict('CONTROLLER','YARD_SUPERVISOR'))):
        return reconciliation_overview(db)

    @app.get('/api/lots/{lot_id}/reconciliation')
    def reconcile_lot(lot_id:str,db:Session=Depends(db_dep),user=Depends(restrict('CONTROLLER','YARD_SUPERVISOR'))):
        lot=db.get(Lot,lot_id)
        if not lot:fail('Material lot not found.',404)
        return lot_reconciliation(db,lot)


    @app.get('/api/dashboard')
    def dashboard(db:Session=Depends(db_dep),user=Depends(auth_user)):
        receipt_pending=db.scalar(select(func.count()).select_from(Receipt).where(Receipt.status=='AWAITING_INSPECTION'))
        transfer_pending=db.scalar(select(func.count()).select_from(Transfer).where(Transfer.status=='DISPATCHED'))
        alerts=db.scalar(select(func.count()).select_from(Discrepancy).where(Discrepancy.status.in_(['OPEN','IN_REVIEW'])))
        stock=db.execute(select(Stock.on_hand_kg,Location.kind).join(Location,Stock.location_id==Location.id)).all()
        return {'receipts_pending':receipt_pending,'transfers_in_transit':transfer_pending,
                'open_discrepancies':alerts,'yard_on_hand_kg':money(sum((Decimal(q) for q,k in stock if k=='YARD'),Decimal(0))),
                'transit_balance_kg':money(sum((Decimal(q) for q,k in stock if k=='TRANSIT'),Decimal(0)))}

    @app.get('/api/audit')
    def audit_list(db:Session=Depends(db_dep),user=Depends(restrict('CONTROLLER','YARD_SUPERVISOR'))):
        events=db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(100)).all()
        return [{'action':e.action,'actor_id':e.actor_id,'actor_name':db.get(User,e.actor_id).display_name if db.get(User,e.actor_id) else 'Unknown', 'entity':e.entity_type,
                 'details':e.details,'time':e.created_at.isoformat()} for e in events]

    @app.post('/api/auth/logout')
    def logout(authorization:str|None=Header(default=None),db:Session=Depends(db_dep),user=Depends(auth_user)):
        token=authorization[7:].strip()
        db.execute(update(AuthSession).where(AuthSession.token_hash==token_hash(token)).values(revoked=True))
        db.commit()
        return {'ok':True}

    app.include_router(manufacturing_routes(db_dep, auth_user))

    web_dir=Path(__file__).resolve().parent.parent/'web'
    @app.get('/',include_in_schema=False)
    def home():return FileResponse(web_dir/'index.html')
    app.mount('/web',StaticFiles(directory=web_dir),name='web')
    return app

app=create_app()
