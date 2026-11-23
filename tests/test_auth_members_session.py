"""AUTH-02: sesión renovable, recuperación de contraseña y gestión de miembros."""
import re
import time
from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models.identity import Membership, TenantInvitation, User, now
from tests.test_identity import client, register  # noqa: F401

PASSWORD = "a-very-long-password"
SEND = "app.api.members.send_email"
SEND_AUTH = "app.api.auth.send_email"


def login(client, email, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def owner(client, email, slug):
    r = register(client, email, slug)
    assert r.status_code == 201, r.json
    token = login(client, email).json["access_token"]
    return r.json["tenant_id"], {"Authorization": "Bearer " + token, "X-Tenant-ID": str(r.json["tenant_id"])}


def _fragment_token(text, path):
    match = re.search(rf"/{path}#token=([A-Za-z0-9_.\-]+)", text)
    assert match, text
    return match.group(1)


# ------------------------------------------------------------------
# Sesión
# ------------------------------------------------------------------

def test_refresh_keeps_original_session_start_and_max_age(client):
    _, headers = owner(client, "sess@example.test", "sess")
    refreshed = client.post("/api/v1/auth/refresh", headers=headers)
    assert refreshed.status_code == 200
    new_headers = {"Authorization": "Bearer " + refreshed.json["access_token"]}
    assert client.get("/api/v1/auth/me", headers=new_headers).status_code == 200
    client.application.config["SESSION_MAX_AGE"] = 1
    try:
        time.sleep(2.1)
        r = client.get("/api/v1/auth/me", headers=new_headers)
        assert r.status_code == 401 and r.json["error"] == "session_expired"
        assert client.post("/api/v1/auth/refresh", headers=new_headers).status_code == 401
    finally:
        client.application.config["SESSION_MAX_AGE"] = 12 * 3600


def test_refresh_requires_valid_token(client):
    assert client.post("/api/v1/auth/refresh").status_code == 401
    assert client.post("/api/v1/auth/refresh", headers={"Authorization": "Bearer nope"}).status_code == 401


# ------------------------------------------------------------------
# Recuperación de contraseña
# ------------------------------------------------------------------

def test_forgot_password_does_not_reveal_accounts(client):
    owner(client, "known@example.test", "known")
    with patch(SEND_AUTH) as send:
        unknown = client.post("/api/v1/auth/password/forgot", json={"email": "nobody@example.test"})
        known = client.post("/api/v1/auth/password/forgot", json={"email": "KNOWN@example.test "})
    assert unknown.status_code == known.status_code == 202
    assert unknown.json == known.json
    assert send.call_count == 1 and send.call_args.kwargs["to_email"] == "known@example.test"


def test_reset_password_single_use_and_revokes_sessions(client):
    _, headers = owner(client, "reset@example.test", "reset")
    with patch(SEND_AUTH) as send:
        client.post("/api/v1/auth/password/forgot", json={"email": "reset@example.test"})
    token = _fragment_token(send.call_args.kwargs["text_body"], "reset-password")
    assert client.post("/api/v1/auth/password/reset", json={"token": token, "password": "short"}).status_code == 422
    ok = client.post("/api/v1/auth/password/reset", json={"token": token, "password": "otra-clave-muy-larga"})
    assert ok.status_code == 200
    # El enlace no se puede reutilizar y la sesión anterior queda revocada.
    again = client.post("/api/v1/auth/password/reset", json={"token": token, "password": "tercera-clave-larga"})
    assert again.status_code == 400
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert login(client, "reset@example.test").status_code == 401
    assert login(client, "reset@example.test", "otra-clave-muy-larga").status_code == 200


def test_reset_rejects_forged_token(client):
    r = client.post("/api/v1/auth/password/reset", json={"token": "x.y.z", "password": "otra-clave-muy-larga"})
    assert r.status_code == 400


# ------------------------------------------------------------------
# Miembros e invitaciones
# ------------------------------------------------------------------

def _invite(client, headers, email, role="staff"):
    with patch(SEND) as send:
        r = client.post("/api/v1/invitations", headers=headers, json={"email": email, "role": role})
    return r, send


def test_invite_new_user_accept_and_role_permissions(client):
    tenant, headers = owner(client, "own-inv@example.test", "own-inv")
    r, send = _invite(client, headers, "Staff@Example.test", "staff")
    assert r.status_code == 201, r.json
    assert r.json["email_sent"] is True and r.json["invitation"]["email"] == "staff@example.test"
    token = _fragment_token(send.call_args.kwargs["text_body"], "invite")
    assert r.json["invite_url"].endswith("#token=" + token)
    with client.application.app_context():
        stored = db.session.scalar(select(TenantInvitation))
        assert stored.token_hash != token and len(stored.token_hash) == 64  # solo el hash

    info = client.post("/api/v1/invitations/lookup", json={"token": token}).json
    assert info["email"] == "staff@example.test" and info["user_exists"] is False and info["role"] == "staff"
    assert client.post("/api/v1/invitations/accept", json={"token": token, "password": "corta"}).status_code == 422
    accepted = client.post("/api/v1/invitations/accept", json={"token": token, "password": "clave-del-operativo"})
    assert accepted.status_code == 200 and accepted.json["tenant_id"] == tenant
    assert client.post("/api/v1/invitations/accept", json={"token": token, "password": "clave-del-operativo"}).status_code == 404

    staff_token = login(client, "staff@example.test", "clave-del-operativo").json["access_token"]
    staff = {"Authorization": "Bearer " + staff_token, "X-Tenant-ID": str(tenant)}
    perms = set(client.get("/api/v1/auth/permissions", headers=staff).json["permissions"])
    assert {"clients.create", "events.create", "quotes.create"} <= perms
    assert not perms & {"billing.manage", "members.manage", "inventory.charges.approve"}
    # Operativo no puede invitar ni contratar.
    assert _invite(client, staff, "other@example.test")[0].status_code == 403
    members = client.get("/api/v1/memberships", headers=headers).json["items"]
    assert {(m["email"], m["role_name"]) for m in members} == {("own-inv@example.test", "owner"), ("staff@example.test", "staff")}


def test_existing_user_must_prove_password(client):
    tenant_a, headers_a = owner(client, "a-own@example.test", "a-own")
    owner(client, "b-user@example.test", "b-co")
    r, send = _invite(client, headers_a, "b-user@example.test", "viewer")
    token = _fragment_token(send.call_args.kwargs["text_body"], "invite")
    assert client.post("/api/v1/invitations/lookup", json={"token": token}).json["user_exists"] is True
    wrong = client.post("/api/v1/invitations/accept", json={"token": token, "password": "no-es-su-clave-123"})
    assert wrong.status_code == 401
    ok = client.post("/api/v1/invitations/accept", json={"token": token, "password": PASSWORD})
    assert ok.status_code == 200
    me = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + login(client, "b-user@example.test").json["access_token"]}).json
    assert tenant_a in me["tenants"] and len(me["tenants"]) == 2


def test_duplicates_revocation_and_expiry(client):
    tenant, headers = owner(client, "dup@example.test", "dup")
    first, send = _invite(client, headers, "x@example.test")
    assert _invite(client, headers, "x@example.test")[0].json["error"] == "invitation_already_pending"
    assert _invite(client, headers, "dup@example.test")[0].json["error"] == "already_member"
    assert _invite(client, headers, "bad-email")[0].status_code == 422
    assert _invite(client, headers, "y@example.test", role="owner")[0].json["error"] == "invalid_role"
    token = _fragment_token(send.call_args.kwargs["text_body"], "invite")
    inv_id = first.json["invitation"]["id"]
    assert client.post(f"/api/v1/invitations/{inv_id}/revoke", headers=headers).status_code == 200
    assert client.post("/api/v1/invitations/accept", json={"token": token, "password": "clave-larga-valida"}).status_code == 404
    # Una invitación caducada se reemplaza al volver a invitar.
    second, send2 = _invite(client, headers, "z@example.test")
    with client.application.app_context():
        inv = db.session.get(TenantInvitation, second.json["invitation"]["id"])
        inv.expires_at = now() - timedelta(minutes=1)
        db.session.commit()
    expired_token = _fragment_token(send2.call_args.kwargs["text_body"], "invite")
    assert client.post("/api/v1/invitations/lookup", json={"token": expired_token}).status_code == 404
    assert _invite(client, headers, "z@example.test")[0].status_code == 201


def test_email_failure_still_returns_shareable_link(client):
    from app.services.email_service import EmailDeliveryError
    _, headers = owner(client, "nomail@example.test", "nomail")
    with patch(SEND, side_effect=EmailDeliveryError("smtp")):
        r = client.post("/api/v1/invitations", headers=headers, json={"email": "p@example.test", "role": "staff"})
    assert r.status_code == 201 and r.json["email_sent"] is False and "#token=" in r.json["invite_url"]


def _accept_new(client, headers, email, role="staff"):
    r, send = _invite(client, headers, email, role)
    token = _fragment_token(send.call_args.kwargs["text_body"], "invite")
    assert client.post("/api/v1/invitations/accept", json={"token": token, "password": "clave-larga-valida"}).status_code == 200
    with client.application.app_context():
        user = db.session.scalar(select(User).where(User.email == email))
        return db.session.scalar(select(Membership).where(Membership.user_id == user.id)).id


def test_change_role_and_deactivate_rules(client):
    tenant, headers = owner(client, "rules@example.test", "rules")
    member_id = _accept_new(client, headers, "m1@example.test", "staff")
    with client.application.app_context():
        owner_membership = db.session.scalar(select(Membership).where(Membership.tenant_id == tenant)
                                             .order_by(Membership.id)).id
    assert client.patch(f"/api/v1/memberships/{member_id}", headers=headers, json={"role": "admin"}).status_code == 200
    assert client.patch(f"/api/v1/memberships/{member_id}", headers=headers, json={"role": "owner"}).json["error"] == "invalid_role"
    assert client.patch(f"/api/v1/memberships/{owner_membership}", headers=headers, json={"role": "viewer"}).json["error"] == "cannot_modify_self"

    m1 = {"Authorization": "Bearer " + login(client, "m1@example.test", "clave-larga-valida").json["access_token"], "X-Tenant-ID": str(tenant)}
    # Un administrador no puede tocar al propietario.
    assert client.post(f"/api/v1/memberships/{owner_membership}/deactivate", headers=m1).json["error"] == "cannot_modify_owner"

    assert client.post(f"/api/v1/memberships/{member_id}/deactivate", headers=headers).status_code == 200
    assert client.get("/api/v1/tenants/current", headers=m1).status_code == 403
    assert client.post(f"/api/v1/memberships/{member_id}/deactivate", headers=headers).json["error"] == "status_unchanged"
    assert client.post(f"/api/v1/memberships/{member_id}/activate", headers=headers).status_code == 200
    assert client.get("/api/v1/tenants/current", headers=m1).status_code == 200


def test_members_endpoints_are_tenant_isolated(client):
    tenant_a, headers_a = owner(client, "iso-a@example.test", "iso-a")
    _, headers_b = owner(client, "iso-b@example.test", "iso-b")
    member_a = _accept_new(client, headers_a, "iso-m@example.test")
    inv, _ = _invite(client, headers_a, "iso-p@example.test")
    inv_id = inv.json["invitation"]["id"]
    assert client.post(f"/api/v1/invitations/{inv_id}/revoke", headers=headers_b).status_code == 404
    assert client.patch(f"/api/v1/memberships/{member_a}", headers=headers_b, json={"role": "viewer"}).status_code == 404
    assert client.post(f"/api/v1/memberships/{member_a}/deactivate", headers=headers_b).status_code == 404
    assert client.get("/api/v1/invitations", headers=headers_b).json["items"] == []
    spoof = dict(headers_b, **{"X-Tenant-ID": str(tenant_a)})
    assert client.get("/api/v1/invitations", headers=spoof).status_code == 403


def test_member_limit_counts_pending_invitations(client):
    from app.services.billing.catalog_seed import seed_free_tier
    from app.models.billing import BillingPlan, BillingPlanEntitlement
    tenant, headers = owner(client, "limit@example.test", "limit")
    with client.application.app_context():
        seed_free_tier()
        free = db.session.scalar(select(BillingPlan).where(BillingPlan.code == "free"))
        ent = db.session.scalar(select(BillingPlanEntitlement).where(
            BillingPlanEntitlement.plan_id == free.id, BillingPlanEntitlement.feature_code == "members"))
        ent.limit_value = 2
        db.session.commit()
    client.application.config["BILLING_ENFORCE_ENTITLEMENTS"] = True
    try:
        assert _invite(client, headers, "l1@example.test")[0].status_code == 201  # 1 activo + 1 pendiente = 2
        denied = _invite(client, headers, "l2@example.test")[0]
        assert denied.status_code == 403 and denied.json["reason"] == "limit_reached" and denied.json["tier"] == "free"
    finally:
        client.application.config["BILLING_ENFORCE_ENTITLEMENTS"] = False


def test_new_owner_has_members_manage(client):
    _, headers = owner(client, "perm-own@example.test", "perm-own")
    perms = client.get("/api/v1/auth/permissions", headers=headers).json["permissions"]
    assert "members.manage" in perms and "billing.manage" in perms
