"""Explicit demo-only factory setup. DO NOT run with real plant accounts."""
import os
from sqlalchemy import select
from .db import new_engine, make_session_factory, Base
from .models import Department, User, MaterialType, Location, Route
from .security import password_hash

DEMO_USERS = [
    ('yard', 'Yard Operator', 'YARD_OPERATOR', 'YARD'),
    ('supervisor', 'Yard Supervisor', 'YARD_SUPERVISOR', 'YARD'),
    ('melting', 'Melting Operator', 'SMS_OPERATOR', 'SMS'),
    ('controller', 'Plant Controller', 'CONTROLLER', None),
    ('refining', 'Refining Operator', 'REFINING_OPERATOR', 'REFINING'),
    ('casting', 'Casting Operator', 'CASTING_OPERATOR', 'CASTING'),
    ('rolling', 'Rolling Operator', 'ROLLING_OPERATOR', 'ROLLING'),
    ('finishing', 'Finishing Operator', 'FINISHING_OPERATOR', 'FINISHING'),
]

def seed(engine=None, password=None):
    if os.getenv('STEELFLOW_DEMO_MODE') != '1':
        raise RuntimeError('Demo seeding disabled. Set STEELFLOW_DEMO_MODE=1 for a local training environment only.')
    engine = engine or new_engine()
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    password = password or os.getenv('STEELFLOW_DEMO_PASSWORD', 'SteelFlowDemo!2026')
    with Session.begin() as db:
        if db.scalar(select(User.id).limit(1)):
            return False
        yard = Department(code='YARD', name='Raw Material Yard')
        sms = Department(code='SMS', name='Steel Melting Shop')
        other = {c:Department(code=c,name=n) for c,n in [('REFINING','Ladle Refining'),('CASTING','Continuous Casting'),('ROLLING','Rolling Mill'),('FINISHING','Finishing & Quality')]}
        db.add_all([yard, sms, *other.values()]); db.flush()
        for uname, name, role, dept_code in DEMO_USERS:
            db.add(User(username=uname, display_name=name, role=role, password_hash=password_hash(password), department_id=yard.id if dept_code=='YARD' else sms.id if dept_code=='SMS' else other[dept_code].id if dept_code in other else None))
        scrap = MaterialType(code='SCRAP-HMS', name='Heavy Melting Scrap', category='SCRAP')
        dri = MaterialType(code='DRI', name='Direct Reduced Iron', category='DRI')
        db.add_all([scrap, dri])
        a = Location(code='YARD-A', name='Yard Storage A', kind='YARD', department_id=yard.id)
        b = Location(code='SMS-RECEIVING', name='Melting Receiving Bay', kind='PROCESS', department_id=sms.id)
        t = Location(code='IN-TRANSIT', name='Material in Transit', kind='TRANSIT', department_id=None)
        db.add_all([a,b,t]); db.flush()
        db.add(Route(source_id=a.id, destination_id=b.id))
    return True

if __name__ == '__main__':
    created = seed()
    print('Demo accounts created.' if created else 'Database already has users; no accounts changed.')
    print('Logins: yard, supervisor, melting, refining, casting, rolling, finishing, controller; password from STEELFLOW_DEMO_PASSWORD (or local demo default).')
