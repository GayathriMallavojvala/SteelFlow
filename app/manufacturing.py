"""Six-stage manufacturing demonstration.

Mass balance is per discrete production run. All streams are kg, and the
unexplained residual is tracked rather than silently classified as scrap.
This module does NOT claim to model real reaction chemistry or moisture changes.
"""
from decimal import Decimal
from uuid import uuid4
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import String, ForeignKey, Numeric, DateTime, Text, CheckConstraint, select, update, func
from sqlalchemy.orm import Mapped, mapped_column, Session
from .db import Base
from .models import Stock, Location, Lot, LedgerEvent, AuditEvent, User

STAGE_DEFS = [
    ('MELTING','Steel Melting Shop','Liquid steel','SMS-RECEIVING'),
    ('REFINING','Ladle Refining','Refined liquid steel',None),
    ('CASTING','Continuous Casting','Steel billets',None),
    ('ROLLING','Rolling Mill','Rolled steel',None),
    ('FINISHING','Quality & Finishing','Finished steel',None),
]
STAGE_PREDECESSOR = {'MELTING':None,'REFINING':'MELTING','CASTING':'REFINING','ROLLING':'CASTING','FINISHING':'ROLLING'}

def now():return datetime.now(timezone.utc)
def uuidstr():return str(uuid4())
def dec(x):return Decimal(str(x)).quantize(Decimal('.001'))
def fmt(x):return f'{dec(x):.3f}'

class Run(Base):
    __tablename__='process_runs'
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=uuidstr)
    reference: Mapped[str] = mapped_column(String(45),unique=True,index=True)
    stage_code: Mapped[str] = mapped_column(String(35),index=True)
    operator_id: Mapped[str] = mapped_column(ForeignKey('app_users.id'))
    input_total_kg: Mapped[Decimal] = mapped_column(Numeric(18,3))
    output_total_kg: Mapped[Decimal] = mapped_column(Numeric(18,3))
    residual_kg: Mapped[Decimal] = mapped_column(Numeric(18,3))
    status: Mapped[str] = mapped_column(String(30))
    evidence_reference: Mapped[str] = mapped_column(String(120))
    notes: Mapped[str] = mapped_column(Text,default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)

class ProcessInput(Base):
    __tablename__='process_inputs'
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=uuidstr)
    run_id: Mapped[str] = mapped_column(ForeignKey('process_runs.id'),index=True)
    source_type: Mapped[str] = mapped_column(String(15))
    source_id: Mapped[str] = mapped_column(String(36))
    source_label: Mapped[str] = mapped_column(String(100))
    material: Mapped[str] = mapped_column(String(150))
    amount_kg: Mapped[Decimal] = mapped_column(Numeric(18,3))
    __table_args__=(CheckConstraint('amount_kg > 0'),)

class ProductBatch(Base):
    __tablename__='produced_batches'
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=uuidstr)
    batch_no: Mapped[str] = mapped_column(String(50),unique=True,index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey('process_runs.id'),index=True)
    stage_code: Mapped[str] = mapped_column(String(35),index=True)
    material: Mapped[str] = mapped_column(String(150))
    output_kind: Mapped[str] = mapped_column(String(20)) # PRODUCT, SCRAP, BYPRODUCT
    initial_kg: Mapped[Decimal] = mapped_column(Numeric(18,3))
    available_kg: Mapped[Decimal] = mapped_column(Numeric(18,3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    __table_args__=(CheckConstraint('available_kg >= 0 AND initial_kg > 0'),)

class RunReview(Base):
    __tablename__='process_run_reviews'
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=uuidstr)
    run_id: Mapped[str] = mapped_column(ForeignKey('process_runs.id'),unique=True)
    note: Mapped[str] = mapped_column(Text)
    evidence_reference: Mapped[str] = mapped_column(String(120))
    reviewed_by: Mapped[str] = mapped_column(ForeignKey('app_users.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)

class InputLine(BaseModel):
    source_type: Literal['RECEIVED_LOT','PRODUCED_BATCH']
    source_id: str
    amount_kg: Decimal = Field(gt=0,max_digits=18,decimal_places=3)

class OutputLine(BaseModel):
    kind: Literal['PRODUCT','SCRAP','BYPRODUCT']
    material: str = Field(min_length=2,max_length=150)
    amount_kg: Decimal = Field(gt=0,max_digits=18,decimal_places=3)

class CreateRun(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True)
    stage_code: Literal['MELTING','REFINING','CASTING','ROLLING','FINISHING']
    inputs: list[InputLine]=Field(min_length=1,max_length=12)
    outputs: list[OutputLine]=Field(min_length=1,max_length=12)
    evidence_reference: str=Field(min_length=3,max_length=120)
    notes: str=Field(default='',max_length=1500)

class ReviewRun(BaseModel):
    note: str=Field(min_length=15,max_length=3000)
    evidence_reference: str=Field(min_length=3,max_length=120)


def routes(db_dep,auth_user):
    api=APIRouter(prefix='/api/production', tags=['Manufacturing'])
    def getrun(db, run):
        ins=db.scalars(select(ProcessInput).where(ProcessInput.run_id==run.id)).all()
        outs=db.scalars(select(ProductBatch).where(ProductBatch.run_id==run.id)).all()
        return {'id':run.id,'reference':run.reference,'stage_code':run.stage_code,'stage_name':next(t[1] for t in STAGE_DEFS if t[0]==run.stage_code),
                'operator':db.get(User,run.operator_id).display_name,'input_total_kg':fmt(run.input_total_kg),'output_total_kg':fmt(run.output_total_kg),
                'residual_kg':fmt(run.residual_kg),'status':run.status,'evidence_reference':run.evidence_reference,'notes':run.notes,
                'created_at':run.created_at.isoformat(),
                'inputs':[{'source_type':i.source_type,'source_id':i.source_id,'source_label':i.source_label,'material':i.material,'amount_kg':fmt(i.amount_kg)} for i in ins],
                'outputs':[{'id':o.id,'batch_no':o.batch_no,'kind':o.output_kind,'material':o.material,'initial_kg':fmt(o.initial_kg),'available_kg':fmt(o.available_kg)} for o in outs]}

    @api.get('/stages')
    def stages(user=Depends(auth_user)):
        return [{'code':code,'name':name,'typical_product':material,'preceding_stage':STAGE_PREDECESSOR[code]} for code,name,material,_ in STAGE_DEFS]

    @api.get('/supply')
    def supply(db:Session=Depends(db_dep),user=Depends(auth_user)):
        # Only eligible sources are shown for each stage. SMS stock from confirmed transfers.
        rows=[]
        for s,lot,loc in db.execute(select(Stock,Lot,Location).join(Lot,Stock.lot_id==Lot.id).join(Location,Stock.location_id==Location.id).where(Location.code=='SMS-RECEIVING',Stock.on_hand_kg>Stock.reserved_kg)).all():
            rows.append({'source_type':'RECEIVED_LOT','id':lot.id,'label':lot.lot_no,'material':'Incoming charge ('+lot.lot_no+')','stage_for':'MELTING','available_kg':fmt(dec(s.on_hand_kg)-dec(s.reserved_kg))})
        for b in db.scalars(select(ProductBatch).where(ProductBatch.available_kg>0,ProductBatch.output_kind=='PRODUCT').order_by(ProductBatch.created_at.desc())).all():
            next_stage=next((code for code,pred in STAGE_PREDECESSOR.items() if pred==b.stage_code),None)
            if next_stage:
                rows.append({'source_type':'PRODUCED_BATCH','id':b.id,'label':b.batch_no,'material':b.material,'stage_for':next_stage,'available_kg':fmt(b.available_kg)})
        return rows

    @api.get('/runs')
    def list_runs(db:Session=Depends(db_dep),user=Depends(auth_user)):
        runs=db.scalars(select(Run).order_by(Run.created_at.desc()).limit(500)).all()
        return [getrun(db,r) for r in runs]

    @api.post('/runs',status_code=201)
    def create_run(body:CreateRun,db:Session=Depends(db_dep),user=Depends(auth_user)):
        if user.role=='CONTROLLER' or user.role=='YARD_SUPERVISOR' or user.role=='YARD_OPERATOR':
            raise HTTPException(403,'Only assigned production operators can record processing.')
        stage=body.stage_code
        assigned={'SMS_OPERATOR':'MELTING','REFINING_OPERATOR':'REFINING','CASTING_OPERATOR':'CASTING','ROLLING_OPERATOR':'ROLLING','FINISHING_OPERATOR':'FINISHING'}
        if assigned.get(user.role)!=stage:raise HTTPException(403,'You can only record production for your assigned stage.')
        if len({(i.source_type,i.source_id) for i in body.inputs}) != len(body.inputs):
            raise HTTPException(400,'Use each source batch only once. Combine duplicate inputs.')
        if not any(o.kind=='PRODUCT' for o in body.outputs):
            raise HTTPException(400,'Record at least one main product output.')
        totalin=sum((i.amount_kg for i in body.inputs),Decimal(0)); totalout=sum((o.amount_kg for o in body.outputs),Decimal(0))
        residual=totalin-totalout
        # Conservative: no outputs exceeding inputs without independently modelled additions.
        if residual<0:raise HTTPException(400,'Recorded output exceeds input. Include all added materials in input lines or correct the measurements.')
        # Per input, acquire available inventory atomically. Rollback all on any shortage.
        sources=[]
        for item in body.inputs:
            if item.source_type=='RECEIVED_LOT':
                if stage!='MELTING':raise HTTPException(400,'Raw received lots are only an input to melting in this demo.')
                loc=db.scalar(select(Location).where(Location.code=='SMS-RECEIVING'))
                src=db.get(Lot,item.source_id)
                if not src or not loc:raise HTTPException(404,'Incoming lot not found.')
                changed=db.execute(update(Stock).where(Stock.lot_id==src.id,Stock.location_id==loc.id,Stock.on_hand_kg-Stock.reserved_kg>=item.amount_kg).values(on_hand_kg=Stock.on_hand_kg-item.amount_kg)).rowcount
                if changed!=1:db.rollback();raise HTTPException(409,'Not enough received stock. Refresh available quantities.')
                sources.append((item,'Incoming lot '+src.lot_no,src.lot_no,loc.id))
            else:
                b=db.get(ProductBatch,item.source_id)
                if not b or b.stage_code!=STAGE_PREDECESSOR[stage] or b.output_kind!='PRODUCT':
                    db.rollback();raise HTTPException(400,'Choose main product stock from the immediately previous stage.')
                changed=db.execute(update(ProductBatch).where(ProductBatch.id==b.id,ProductBatch.available_kg>=item.amount_kg).values(available_kg=ProductBatch.available_kg-item.amount_kg)).rowcount
                if changed!=1:db.rollback();raise HTTPException(409,'That batch no longer has enough available material.')
                sources.append((item,b.material,b.batch_no,None))
        run=Run(reference='RUN-'+uuid4().hex[:12].upper(),stage_code=stage,operator_id=user.id,input_total_kg=totalin,output_total_kg=totalout,
                residual_kg=residual,status='NEEDS_REVIEW' if residual else 'BALANCED',evidence_reference=body.evidence_reference,notes=body.notes)
        db.add(run);db.flush()
        for item,mat,label,location in sources:
            db.add(ProcessInput(run_id=run.id,source_type=item.source_type,source_id=item.source_id,source_label=label,material=mat,amount_kg=item.amount_kg))
            if location:
                db.add(LedgerEvent(event_group=run.id,lot_id=item.source_id,location_id=location,delta_kg=-item.amount_kg,action='PROCESS_CONSUME',reference_id=run.id,created_by=user.id))
        for item in body.outputs:
            db.add(ProductBatch(batch_no='BCH-'+uuid4().hex[:12].upper(),run_id=run.id,stage_code=stage,material=item.material,
                                output_kind=item.kind,initial_kg=item.amount_kg,available_kg=item.amount_kg))
        db.add(AuditEvent(actor_id=user.id,entity_type='Run',entity_id=run.id,action='PROCESS_RUN_RECORDED',
                          details={'stage':stage,'input_kg':fmt(totalin),'outputs_kg':fmt(totalout),'unexplained_kg':fmt(residual),'evidence':body.evidence_reference}))
        db.commit();return getrun(db,run)

    @api.get('/runs/{run_id}')
    def detail(run_id:str,db:Session=Depends(db_dep),user=Depends(auth_user)):
        r=db.get(Run,run_id)
        if not r:raise HTTPException(404,'Production run not found.')
        return getrun(db,r)

    @api.post('/runs/{run_id}/review')
    def review(run_id:str,body:ReviewRun,db:Session=Depends(db_dep),user=Depends(auth_user)):
        if user.role!='CONTROLLER':raise HTTPException(403,'Only the plant controller may review production discrepancies.')
        changed=db.execute(update(Run).where(Run.id==run_id,Run.status=='NEEDS_REVIEW').values(status='UNDER_INVESTIGATION')).rowcount
        if changed!=1:db.rollback();raise HTTPException(409,'No open production discrepancy found for this run.')
        db.add(RunReview(run_id=run_id,note=body.note,evidence_reference=body.evidence_reference,reviewed_by=user.id))
        db.add(AuditEvent(actor_id=user.id,entity_type='Run',entity_id=run_id,action='PROCESS_RUN_REVIEWED',details={'note':body.note,'evidence':body.evidence_reference}))
        db.commit()
        return {'status':'UNDER_INVESTIGATION','message':'Investigation recorded. Original quantities were not modified.'}

    @api.get('/genealogy/{batch_id}')
    def genealogy(batch_id:str,db:Session=Depends(db_dep),user=Depends(auth_user)):
        b=db.get(ProductBatch,batch_id)
        if not b:raise HTTPException(404,'Batch not found.')
        nodes=[];edges=[];seen=set()
        def walk(batch,depth=0):
            if depth>25 or batch.id in seen:return
            seen.add(batch.id)
            nodes.append({'id':batch.id,'label':batch.batch_no,'material':batch.material,'stage':batch.stage_code,'amount_kg':fmt(batch.initial_kg),'kind':batch.output_kind})
            for inp in db.scalars(select(ProcessInput).where(ProcessInput.run_id==batch.run_id)).all():
                edges.append({'from':inp.source_id,'to':batch.id,'kg_consumed':fmt(inp.amount_kg)})
                if inp.source_type=='PRODUCED_BATCH':
                    parent=db.get(ProductBatch,inp.source_id)
                    if parent:walk(parent,depth+1)
                elif inp.source_id not in seen:
                    seen.add(inp.source_id)
                    nodes.append({'id':inp.source_id,'label':inp.source_label,'material':inp.material,'stage':'RAW MATERIAL','amount_kg':fmt(inp.amount_kg),'kind':'INPUT'})
        walk(b)
        return {'batch_no':b.batch_no,'nodes':nodes,'edges':edges,'note':'Edges represent linked input contributions, not one-to-one physical identity of atoms.'}

    @api.get('/overview')
    def overview(db:Session=Depends(db_dep),user=Depends(auth_user)):
        runs=db.scalars(select(Run).order_by(Run.created_at.desc())).all()
        bystage=[]
        for code,name,_,_ in STAGE_DEFS:
            subset=[r for r in runs if r.stage_code==code]
            bystage.append({'code':code,'name':name,'runs':len(subset),'input_kg':fmt(sum((dec(r.input_total_kg) for r in subset),Decimal(0))),
                            'output_kg':fmt(sum((dec(r.output_total_kg) for r in subset),Decimal(0))),
                            'unexplained_kg':fmt(sum((dec(r.residual_kg) for r in subset),Decimal(0))),
                            'open_cases':sum(r.status in ('NEEDS_REVIEW','UNDER_INVESTIGATION') for r in subset)})
        return {'stages':bystage,'total_runs':len(runs),'open_process_cases':sum(r.status in ('NEEDS_REVIEW','UNDER_INVESTIGATION') for r in runs),
                'available_finished_kg':fmt(db.scalar(select(func.coalesce(func.sum(ProductBatch.available_kg),0)).where(ProductBatch.stage_code=='FINISHING',ProductBatch.output_kind=='PRODUCT')) or 0),
                'limitations':'Stage-level residuals are unaccounted mass in a simplified batch model. They are not verified physical losses.'}
    return api
