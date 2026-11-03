"""Run from inside Docker: docker compose exec app python -m app.verify_postgres

Inserts a unique demonstration receipt and tests the linked material route.
"""
from uuid import uuid4
from fastapi.testclient import TestClient
from .db import new_engine
from .main import app

PASSWORD = None

def main():
    import os
    url=os.getenv('DATABASE_URL','')
    if not url.startswith('postgresql'):
        raise SystemExit('PostgreSQL DATABASE_URL required. This script never uses SQLite.')
    engine=new_engine(url)
    with engine.connect() as conn:
        from sqlalchemy import text
        version=conn.scalar(text('SELECT current_setting(\'server_version\')'))
    password=os.getenv('STEELFLOW_DEMO_PASSWORD','SteelFlowDemo!2026')
    c=TestClient(app)
    def role(user):
        r=c.post('/api/auth/login',json={'username':user,'password':password});assert r.status_code==200,r.text
        return {'Authorization':'Bearer '+r.json()['access_token']}
    yard,supervisor,melting,controller=[role(u) for u in ('yard','supervisor','melting','controller')]
    ticket='PG-VERIFY-'+uuid4().hex[:14].upper()
    r=c.post('/api/receipts',headers=yard,json={'material_code':'SCRAP-HMS','supplier':'Database verification',
       'delivery_reference':'PG-VERIFY','vehicle_number':'TS09AB1234','weighbridge_ticket':ticket,
       'gross_kg':'32800','tare_kg':'12800'})
    assert r.status_code==201,r.text
    rid=r.json()['id'];assert r.json()['net_kg']=='20000.000'
    release=c.post('/api/receipts/'+rid+'/review',headers=supervisor,
                   json={'decision':'RELEASED','reason':'Verified test lot'})
    assert release.status_code==200,release.text
    stocks=c.get('/api/inventory',headers=controller).json()
    lots={x['lot_id']:x for x in stocks if x['location_code']=='YARD-A'}
    # Unique test lot can be identified from underlying receipt relation using SQL
    from .models import Lot
    from sqlalchemy.orm import Session
    from sqlalchemy import select
    with Session(engine) as db:
        lot=db.scalar(select(Lot).where(Lot.receipt_id==rid))
        assert lot and lot.id in lots
    t=c.post('/api/transfers',headers=yard,json={'lot_id':lot.id,'quantity_kg':'10000'})
    assert t.status_code==201,t.text
    tid=t.json()['id']
    d=c.post('/api/transfers/'+tid+'/dispatch',headers=yard,json={'evidence_reference':'PG-OUT-'+ticket,'measured_kg':'10000'})
    assert d.status_code==200,d.text
    m=c.post('/api/transfers/'+tid+'/receive',headers=melting,
             json={'received_kg':'9800','evidence_reference':'PG-IN-'+ticket})
    assert m.status_code==200,m.text
    assert m.json()['difference_kg']=='200.000'
    alerts=c.get('/api/discrepancies',headers=controller).json()
    assert any(x['transfer_id']==tid and x['difference_kg']=='200.000' for x in alerts)
    print(f'PASS PostgreSQL {version} | ticket={ticket} | 20,000 kg received; 10,000 kg dispatched; 9,800 kg confirmed; 200 kg under review')

if __name__=='__main__': main()
