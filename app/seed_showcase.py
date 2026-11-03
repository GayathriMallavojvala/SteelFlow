"""Opt-in repeatable sample storyline. For local demo mode only. Not plant data."""
import os
from fastapi.testclient import TestClient
from .seed_demo import seed
from .main import create_app


def populate():
    if os.environ.get('STEELFLOW_DEMO_MODE')!='1':
        raise RuntimeError('Set STEELFLOW_DEMO_MODE=1. This script must never run against production.')
    seed()
    app=create_app(); c=TestClient(app)
    password=os.environ.get('STEELFLOW_DEMO_PASSWORD','SteelFlowDemo!2026')
    h={}
    for account in ('yard','supervisor','melting','refining','casting','rolling','finishing','controller'):
        r=c.post('/api/auth/login',json={'username':account,'password':password});r.raise_for_status()
        h[account]={'Authorization':'Bearer '+r.json()['access_token']}
    existing=c.get('/api/receipts',headers=h['controller']).json()
    if any(r.get('ticket')=='DEMO-STEEL-2026' for r in existing):
        print('Sample dataset already exists; no duplicates created.');return False
    def post(url,who,data):
        r=c.post(url,headers=h[who],json=data)
        if r.status_code>=400:raise RuntimeError(f'{who} {url}: {r.status_code} {r.text}')
        return r.json()
    receipt=post('/api/receipts','yard',{'material_code':'SCRAP-HMS','supplier':'Sample Iron Suppliers','delivery_reference':'PO-DEMO-001',
        'vehicle_number':'TS09DEMO1','weighbridge_ticket':'DEMO-STEEL-2026','gross_kg':'12000','tare_kg':'2000'})
    post('/api/receipts/'+receipt['id']+'/review','supervisor',{'decision':'RELEASED','reason':'Simulated material release for training'})
    lot=next(v for v in c.get('/api/inventory',headers=h['yard']).json() if v['location_kind']=='YARD' and v['on_hand_kg']=='10000.000')
    tr=post('/api/transfers','yard',{'lot_id':lot['lot_id'],'quantity_kg':'10000'})
    post('/api/transfers/'+tr['id']+'/dispatch','yard',{'measured_kg':'10000','evidence_reference':'DEMO-WB-OUT'})
    post('/api/transfers/'+tr['id']+'/receive','melting',{'received_kg':'10000','evidence_reference':'DEMO-WB-IN'})
    stages=[('MELTING','melting','Liquid steel',[('PRODUCT','Liquid steel','9000'),('BYPRODUCT','Steel slag','900'),('BYPRODUCT','Dust','100')]),
            ('REFINING','refining','Refined steel',[('PRODUCT','Refined liquid steel','8900'),('BYPRODUCT','Refining slag','100')]),
            ('CASTING','casting','Steel billets',[('PRODUCT','Steel billets','8800'),('SCRAP','Casting crop scrap','100')]),
            ('ROLLING','rolling','Rolled steel',[('PRODUCT','Rolled steel bars','8540'),('SCRAP','Crop scrap','150'),('BYPRODUCT','Mill scale','100')]),
            ('FINISHING','finishing','Finished steel',[('PRODUCT','Finished steel bars','8450'),('SCRAP','Finishing rejects','90')])]
    src=next(x for x in c.get('/api/production/supply',headers=h['melting']).json() if x['stage_for']=='MELTING' and x['id']==lot['lot_id'])
    for stage,user,primary,outputs in stages:
        r=post('/api/production/runs',user,{'stage_code':stage,
            'inputs':[{'source_type':src['source_type'],'source_id':src['id'],'amount_kg':src['available_kg']}],
            'outputs':[{'kind':kind,'material':mat,'amount_kg':qty} for kind,mat,qty in outputs],
            'evidence_reference':'DEMO-RUN-'+stage,'notes':'Synthetic example; not steel-plant engineering data.'})
        if stage!='FINISHING':
            main=next(o for o in r['outputs'] if o['kind']=='PRODUCT')
            src=next(x for x in c.get('/api/production/supply',headers=h['controller']).json() if x['id']==main['id'])
    # An additional imbalanced run, using a second delivery, makes the investigation view meaningful.
    extra=post('/api/receipts','yard',{'material_code':'DRI','supplier':'Sample DRI Supplier','delivery_reference':'PO-DEMO-002',
        'vehicle_number':'TS09DEMO2','weighbridge_ticket':'DEMO-STEEL-2026-2','gross_kg':'6800','tare_kg':'1800'})
    post('/api/receipts/'+extra['id']+'/review','supervisor',{'decision':'RELEASED','reason':'Training release confirmed'})
    lot2=next(v for v in c.get('/api/inventory',headers=h['yard']).json() if v['location_kind']=='YARD' and v['on_hand_kg']=='5000.000')
    tr2=post('/api/transfers','yard',{'lot_id':lot2['lot_id'],'quantity_kg':'5000'})
    post('/api/transfers/'+tr2['id']+'/dispatch','yard',{'measured_kg':'5000','evidence_reference':'DEMO-WB-OUT-2'})
    post('/api/transfers/'+tr2['id']+'/receive','melting',{'received_kg':'5000','evidence_reference':'DEMO-WB-IN-2'})
    post('/api/production/runs','melting',{'stage_code':'MELTING','inputs':[{'source_type':'RECEIVED_LOT','source_id':lot2['lot_id'],'amount_kg':'5000'}],
        'outputs':[{'kind':'PRODUCT','material':'Liquid steel','amount_kg':'4400'},{'kind':'BYPRODUCT','material':'Slag','amount_kg':'450'}],
        'evidence_reference':'DEMO-EXCEPTION-01','notes':'150 kg deliberately unexplained; investigate measurement records.'})
    print('Sample data ready: 2 receipts, 2 transfers, 5-stage production chain, one 150 kg production anomaly.')
    return True

if __name__=='__main__':populate()
