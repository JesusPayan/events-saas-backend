import pytest
from app import create_app
from app.extensions import db
from app.models import Membership, Role

@pytest.fixture
def client():
    app = create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':'sqlite:///:memory:','SECRET_KEY':'test-key'})
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()

def register(client,email,slug):
    return client.post('/api/v1/auth/register',json={'email':email,'password':'a-very-long-password','company_name':'Empresa '+slug,'slug':slug})

def token(client,email):
    response=client.post('/api/v1/auth/login',json={'email':email,'password':'a-very-long-password'})
    assert response.status_code == 200
    return response.json['access_token']

def test_register_login_and_isolation(client):
    a=register(client,'a@example.com','empresa-a'); b=register(client,'b@example.com','empresa-b')
    assert a.status_code == b.status_code == 201
    ta=a.json['tenant_id']; tb=b.json['tenant_id']; bearer='Bearer '+token(client,'a@example.com')
    assert client.get('/api/v1/tenants/current',headers={'Authorization':bearer,'X-Tenant-ID':str(ta)}).status_code == 200
    assert client.get('/api/v1/tenants/current',headers={'Authorization':bearer,'X-Tenant-ID':str(tb)}).status_code == 403
    assert client.get('/api/v1/memberships',headers={'Authorization':bearer,'X-Tenant-ID':str(tb)}).status_code == 403
    assert client.get('/api/v1/tenants/current',headers={'X-Tenant-ID':str(ta)}).status_code == 401

def test_duplicate_and_wrong_password(client):
    assert register(client,'a@example.com','empresa-a').status_code == 201
    assert register(client,'a@example.com','empresa-b').status_code == 409
    assert client.post('/api/v1/auth/login',json={'email':'a@example.com','password':'incorrect'}).status_code == 401

def test_cross_tenant_role_rejected(client):
    a=register(client,'a@example.com','empresa-a').json
    b=register(client,'b@example.com','empresa-b').json
    with client.application.app_context():
        role_b=db.session.query(Role).filter_by(tenant_id=b['tenant_id']).one()
        member_a=db.session.query(Membership).filter_by(tenant_id=a['tenant_id']).one()
        member_a.role_id=role_b.id
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
