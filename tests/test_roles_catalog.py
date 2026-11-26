"""ROLES-01 + CAT-01: roles con alcance, aislamiento entre organizaciones,
promotores, accesos delegados, categorías y cotizaciones mixtas."""
import re
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models.platform import AuditEvent
from app.services.catalog_service import seed_categories
from app.services.platform_service import bootstrap_owner
from tests.test_identity import client, register  # noqa: F401

PASSWORD = "a-very-long-password"
SEND_MEMBERS = "app.api.members.send_email"
SEND_PLATFORM = "app.api.platform.send_email"


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------

def login(client, email, password=PASSWORD):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.json
    return {"Authorization": "Bearer " + r.json["access_token"]}


def owner(client, email, slug, ref=None):
    body = {"email": email, "password": PASSWORD, "slug": slug, "company_name": f"Empresa {slug}"}
    if ref:
        body["ref"] = ref
    r = client.post("/api/v1/auth/register", json=body)
    assert r.status_code == 201, r.json
    headers = login(client, email)
    return r.json["tenant_id"], {**headers, "X-Tenant-ID": str(r.json["tenant_id"])}


def make_owner(client, email):
    with client.application.app_context():
        bootstrap_owner(email)


def grant(client, headers, email, role):
    return client.post("/api/v1/platform/roles", json={"email": email, "role": role}, headers=headers)


def audit_actions(client, tenant_id=None):
    with client.application.app_context():
        query = select(AuditEvent.action)
        if tenant_id:
            query = query.where(AuditEvent.tenant_id == tenant_id)
        return list(db.session.scalars(query).all())


@pytest.fixture
def seeded(client):
    with client.application.app_context():
        seed_categories()
    return client


def categories(client, headers):
    items = client.get("/api/v1/catalog/categories", headers=headers).json["items"]
    return {c["slug"]: c["id"] for c in items}


def new_event(client, headers, starts="2026-12-12T18:00:00-06:00", ends="2026-12-13T02:00:00-06:00"):
    c = client.post("/api/v1/clients", json={"first_name": "Ana", "last_name": "López"}, headers=headers)
    assert c.status_code == 201, c.json
    e = client.post("/api/v1/events", json={
        "client_id": c.json["id"], "event_type": "social", "name": "Boda Martínez",
        "starts_at": starts, "ends_at": ends}, headers=headers)
    assert e.status_code == 201, e.json
    return c.json["id"], e.json["id"]


# ----------------------------------------------------------------------------
# Dueño, administradores y promotores
# ----------------------------------------------------------------------------

def test_owner_manages_admins_and_promoter_cannot_escalate(client):
    _, owner_h = owner(client, "dueno@example.test", "dueno")
    owner(client, "admin@example.test", "admin-co")
    owner(client, "promo@example.test", "promo-co")
    make_owner(client, "dueno@example.test")
    h_owner = login(client, "dueno@example.test")

    assert grant(client, h_owner, "admin@example.test", "platform_admin").status_code == 201
    h_admin = login(client, "admin@example.test")
    # El administrador gestiona promotores, pero no administradores ni dueños.
    assert grant(client, h_admin, "promo@example.test", "promoter").status_code == 201
    assert grant(client, h_admin, "promo@example.test", "platform_admin").status_code == 403
    assert grant(client, h_admin, "admin@example.test", "platform_owner").status_code == 409
    # Roles reservados existen, pero aún no se asignan.
    assert grant(client, h_owner, "promo@example.test", "auditor").status_code == 422

    h_promo = login(client, "promo@example.test")
    for role in ("platform_admin", "platform_owner", "promoter"):
        assert grant(client, h_promo, "promo@example.test", role).status_code == 403
    assert client.get("/api/v1/platform/roles", headers=h_promo).status_code == 403
    assert client.get("/api/v1/platform/organizations", headers=h_promo).status_code == 403
    assert client.get("/api/v1/billing/admin/subscriptions", headers=h_promo).status_code == 403
    me = client.get("/api/v1/auth/me", headers=h_promo).json
    assert me["platform"]["roles"] == ["promoter"]

    actions = audit_actions(client)
    assert actions.count("platform_role.grant") >= 3  # dueño inicial + admin + promotor


def test_platform_never_left_without_owner(client):
    owner(client, "o1@example.test", "own-one")
    owner(client, "o2@example.test", "own-two")
    make_owner(client, "o1@example.test")
    h1 = login(client, "o1@example.test")
    roles = client.get("/api/v1/platform/roles", headers=h1).json["items"]
    owner_row = next(r for r in roles if r["role"] == "platform_owner")
    assert client.post(f"/api/v1/platform/roles/{owner_row['id']}/revoke", headers=h1).status_code == 409
    with client.application.app_context():
        from app.services.platform_service import PlatformError
        with pytest.raises(PlatformError):
            bootstrap_owner("o2@example.test")  # ya hay dueño

    r = client.post("/api/v1/platform/owner/transfer", json={"email": "o2@example.test"}, headers=h1)
    assert r.status_code == 200, r.json
    roles = {(x["email"], x["role"]) for x in client.get(
        "/api/v1/platform/roles", headers=login(client, "o2@example.test")).json["items"]}
    assert ("o2@example.test", "platform_owner") in roles
    assert ("o1@example.test", "platform_owner") not in roles
    assert ("o1@example.test", "platform_admin") in roles  # conserva la administración
    # El anterior dueño ya no puede transferir.
    assert client.post("/api/v1/platform/owner/transfer", json={"email": "o1@example.test"},
                       headers=login(client, "o1@example.test")).status_code == 403
    assert "platform_owner.transfer" in audit_actions(client)


def test_platform_invitation_creates_account_with_role(client):
    owner(client, "boss@example.test", "boss")
    make_owner(client, "boss@example.test")
    h = login(client, "boss@example.test")
    with patch(SEND_PLATFORM) as send:
        r = grant(client, h, "nuevo.promotor@example.test", "promoter")
    assert r.status_code == 201 and r.json["invited"] is True
    token = re.search(r"#token=([A-Za-z0-9_\-]+)", send.call_args.kwargs["text_body"]).group(1)
    assert client.post("/api/v1/platform/invitations/lookup", json={"token": token}).json["role"] == "promoter"
    ok = client.post("/api/v1/platform/invitations/accept", json={"token": token, "password": PASSWORD})
    assert ok.status_code == 200, ok.json
    me = client.get("/api/v1/auth/me", headers=login(client, "nuevo.promotor@example.test")).json
    assert me["platform"]["roles"] == ["promoter"] and me["tenants"] == []


# ----------------------------------------------------------------------------
# Aislamiento entre organizaciones (incluye llamadas directas a la API)
# ----------------------------------------------------------------------------

def test_org_admin_cannot_read_or_modify_other_org(seeded):
    client = seeded
    tenant_a, h_a = owner(client, "a@example.test", "org-a")
    tenant_b, h_b = owner(client, "b@example.test", "org-b")
    cats = categories(client, h_a)
    _, event_a = new_event(client, h_a)
    provider_a = client.post("/api/v1/providers", json={"name": "Banquetes A"}, headers=h_a).json["provider"]
    offer_a = client.post("/api/v1/catalog/offers", json={
        "name": "Banquete", "category_id": cats["banquetes-y-catering"], "provider_id": provider_a["id"],
        "pricing_mode": "per_person", "unit_price": "350.00", "fulfillment_type": "manual",
        "status": "published"}, headers=h_a)
    assert offer_a.status_code == 201, offer_a.json
    client_a = client.get("/api/v1/clients", headers=h_a).json["items"][0]["id"]
    quote_a = client.post("/api/v1/quotes", json={
        "client_id": client_a, "event_id": event_a,
        "items": [{"offer_id": offer_a.json["offer"]["id"], "quantity": "80", "guests": 80}]}, headers=h_a)
    assert quote_a.status_code == 201, quote_a.json
    item_a = quote_a.json["items"][0]["id"]

    # B con su token apuntando a la organización A: rechazado en lecturas, búsquedas y exportaciones.
    forged = {**h_b, "X-Tenant-ID": str(tenant_a)}
    for path in ("/api/v1/clients?search=Ana", "/api/v1/quotes", f"/api/v1/quotes/{quote_a.json['id']}",
                 "/api/v1/catalog/offers", "/api/v1/providers", "/api/v1/access-grants",
                 "/api/v1/memberships", "/api/v1/inventory/items?search=x",
                 "/api/v1/inventory/reports/availability/export?starts_at=2026-01-01T00:00:00"
                 "&ends_at=2026-01-02T00:00:00",
                 f"/api/v1/quotes/{quote_a.json['id']}/pdf"):
        assert client.get(path, headers=forged).status_code == 403, path
    assert client.patch(f"/api/v1/catalog/offers/{offer_a.json['offer']['id']}", json={"name": "x"},
                        headers=forged).status_code == 403
    # B en su propia organización con identificadores de A: no existen para B.
    assert client.get(f"/api/v1/quotes/{quote_a.json['id']}", headers=h_b).status_code == 404
    assert client.patch(f"/api/v1/catalog/offers/{offer_a.json['offer']['id']}", json={"name": "x"},
                        headers=h_b).status_code == 404
    assert client.patch(f"/api/v1/providers/{provider_a['id']}", json={"name": "x"},
                        headers=h_b).status_code == 404
    assert client.patch(f"/api/v1/quotes/{quote_a.json['id']}/items/{item_a}", json={"unit_price": "1.00"},
                        headers=h_b).status_code == 404
    # B no puede usar la oferta ni el proveedor de A en sus cotizaciones u ofertas.
    client_b, event_b = new_event(client, h_b)
    r = client.post("/api/v1/quotes", json={"client_id": client_b, "event_id": event_b,
                                            "items": [{"offer_id": offer_a.json["offer"]["id"], "quantity": "1"}]},
                    headers=h_b)
    assert r.status_code == 404
    r = client.post("/api/v1/catalog/offers", json={
        "name": "x", "category_id": cats["video"], "provider_id": provider_a["id"],
        "pricing_mode": "quote", "fulfillment_type": "manual"}, headers=h_b)
    assert r.status_code == 404
    # El catálogo de B no muestra las ofertas de A.
    assert client.get("/api/v1/catalog/offers", headers=h_b).json["total"] == 0


def test_unauthenticated_calls_are_rejected():
    from app import create_app
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "SECRET_KEY": "k", "JWT_SECRET_KEY": "j", "CHECK_DB_ON_STARTUP": False})
    public = ("/public/", "/health", "/ready", "/auth/login", "/auth/register", "/auth/refresh",
              "/auth/password/", "/invitations/lookup", "/invitations/accept", "/mercadopago/webhook", "/e2e/",
              "/contract-signing", "/sign", "/docs", "/swagger", "/openapi", "/signature")
    with app.test_client() as c:
        checked = 0
        for rule in app.url_map.iter_rules():
            path = rule.rule
            if not path.startswith("/api/v1") or any(p in path for p in public):
                continue
            url = re.sub(r"<(?:int:)?[^>]+>", "1", path)
            for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
                r = c.open(url, method=method, json={})
                assert r.status_code in (400, 401, 403, 405, 422), (method, path, r.status_code)
                assert r.status_code != 200
                checked += 1
        assert checked > 100


# ----------------------------------------------------------------------------
# Promotores y accesos delegados
# ----------------------------------------------------------------------------

def test_promoter_tracks_referrals_without_private_data(client):
    owner(client, "root@example.test", "root")
    make_owner(client, "root@example.test")
    owner(client, "promoter@example.test", "promoter-home")
    assert grant(client, login(client, "root@example.test"), "promoter@example.test", "promoter").status_code == 201
    h_p = login(client, "promoter@example.test")

    summary = client.get("/api/v1/promoter/summary", headers=h_p).json
    code = summary["code"]
    assert summary["link"].endswith(f"/register?ref={code}")
    prospect = client.post("/api/v1/promoter/prospects", json={
        "company_name": "Eventos Sol", "contact_email": "sol@example.test"}, headers=h_p)
    assert prospect.status_code == 201
    with patch(SEND_PLATFORM):
        assert client.post(f"/api/v1/promoter/prospects/{prospect.json['prospect']['id']}/invite",
                           headers=h_p).json["prospect"]["status"] == "invited"

    referred_id, h_ref = owner(client, "sol@example.test", "eventos-sol", ref=code)
    client.post("/api/v1/clients", json={"first_name": "Secreto", "last_name": "Cliente"}, headers=h_ref)
    referrals = client.get("/api/v1/promoter/referrals", headers=h_p).json["items"]
    assert [r["tenant_id"] for r in referrals] == [referred_id]
    assert set(referrals[0]) == {"tenant_id", "organization", "status", "registered_at",
                                 "subscription_status", "prospect_id"}
    prospects = client.get("/api/v1/promoter/prospects", headers=h_p).json["items"]
    assert prospects[0]["status"] == "registered" and prospects[0]["tenant_id"] == referred_id

    # El referido no da acceso a los datos de la organización referida.
    forged = {**h_p, "X-Tenant-ID": str(referred_id)}
    for path in ("/api/v1/clients", "/api/v1/quotes", "/api/v1/catalog/offers", "/api/v1/events",
                 "/api/v1/tenants/current"):
        assert client.get(path, headers=forged).status_code == 403, path
    # Otro promotor no ve los prospectos ajenos.
    owner(client, "otro@example.test", "otro-home")
    grant(client, login(client, "root@example.test"), "otro@example.test", "promoter")
    h_o = login(client, "otro@example.test")
    assert client.get("/api/v1/promoter/prospects", headers=h_o).json["items"] == []
    assert client.patch(f"/api/v1/promoter/prospects/{prospect.json['prospect']['id']}",
                        json={"notes": "x"}, headers=h_o).status_code == 404

    # Capacitación: el administrador concede acceso temporal de solo lectura, con vencimiento y revocación.
    bad = client.post("/api/v1/access-grants", json={"email": "otro@example.test", "purpose": "training",
                                                     "days": 3}, headers=h_ref)
    assert bad.status_code == 422  # no es el promotor que refirió a la organización
    g = client.post("/api/v1/access-grants", json={"email": "promoter@example.test", "purpose": "training",
                                                   "days": 3, "reason": "Capacitación inicial"}, headers=h_ref)
    assert g.status_code == 201, g.json
    assert client.get("/api/v1/clients", headers=forged).status_code == 200
    assert client.get("/api/v1/auth/permissions", headers=forged).json["delegated"] is True
    assert client.post("/api/v1/clients", json={"first_name": "X", "last_name": "Y"},
                       headers=forged).status_code == 403  # solo lectura
    assert client.get("/api/v1/memberships", headers=forged).status_code == 403
    assert client.post("/api/v1/access-grants/" + str(g.json["grant"]["id"]) + "/revoke",
                       headers=h_ref).status_code == 200
    assert client.get("/api/v1/clients", headers=forged).status_code == 403
    actions = audit_actions(client, referred_id)
    assert {"access_grant.create", "delegated_access.use", "access_grant.revoke"} <= set(actions)


def test_multiple_roles_keep_scope_and_revocation_removes_access(client):
    owner(client, "root2@example.test", "root2")
    make_owner(client, "root2@example.test")
    tenant_a, h_a = owner(client, "multi@example.test", "multi-a")
    tenant_b, _ = owner(client, "other@example.test", "multi-b")
    h_root = login(client, "root2@example.test")
    assert grant(client, h_root, "multi@example.test", "platform_admin").status_code == 201
    assert grant(client, h_root, "multi@example.test", "promoter").status_code == 201
    h_multi = login(client, "multi@example.test")

    # Plataforma: ve organizaciones (sin datos privados). Organización propia: acceso completo.
    assert client.get("/api/v1/platform/organizations", headers=h_multi).status_code == 200
    assert client.get("/api/v1/promoter/summary", headers=h_multi).status_code == 200
    assert client.get("/api/v1/clients", headers=h_a).status_code == 200
    # Ser administrador de plataforma no abre los datos privados de otra organización.
    assert client.get("/api/v1/clients", headers={**h_multi, "X-Tenant-ID": str(tenant_b)}).status_code == 403
    # Soporte: solo con permiso explícito de la organización y quedando registrado.
    h_other = {**login(client, "other@example.test"), "X-Tenant-ID": str(tenant_b)}
    assert client.post("/api/v1/access-grants", json={"email": "multi@example.test", "purpose": "support",
                                                      "days": 1}, headers=h_other).status_code == 201
    assert client.get("/api/v1/clients", headers={**h_multi, "X-Tenant-ID": str(tenant_b)}).status_code == 200
    assert "delegated_access.use" in audit_actions(client, tenant_b)

    # Revocar el rol de administrador retira solo ese alcance.
    rows = client.get("/api/v1/platform/roles", headers=h_root).json["items"]
    admin_row = next(r for r in rows if r["email"] == "multi@example.test" and r["role"] == "platform_admin")
    assert client.post(f"/api/v1/platform/roles/{admin_row['id']}/revoke", headers=h_root).status_code == 200
    assert client.get("/api/v1/platform/organizations", headers=h_multi).status_code == 403
    assert client.get("/api/v1/promoter/summary", headers=h_multi).status_code == 200
    assert client.get("/api/v1/clients", headers=h_a).status_code == 200


def test_suspended_organization_blocks_operations_and_is_audited(client):
    owner(client, "root3@example.test", "root3")
    make_owner(client, "root3@example.test")
    tenant, h_t = owner(client, "susp@example.test", "susp")
    h_root = login(client, "root3@example.test")
    r = client.patch(f"/api/v1/platform/organizations/{tenant}/status",
                     json={"status": "suspended", "reason": "Falta de pago"}, headers=h_root)
    assert r.status_code == 200 and r.json["organization"]["status"] == "suspended"
    blocked = client.get("/api/v1/clients", headers=h_t)
    assert blocked.status_code == 403 and blocked.json["error"] == "tenant_suspended"
    client.patch(f"/api/v1/platform/organizations/{tenant}/status", json={"status": "active"}, headers=h_root)
    assert client.get("/api/v1/clients", headers=h_t).status_code == 200
    assert {"organization.suspend", "organization.activate"} <= set(audit_actions(client, tenant))
    audit = client.get(f"/api/v1/platform/audit?tenant_id={tenant}", headers=h_root).json["items"]
    assert audit[0]["actor_email"] == "root3@example.test"


def test_platform_creates_organization_with_owner_invitation(client):
    owner(client, "root4@example.test", "root4")
    make_owner(client, "root4@example.test")
    h_root = login(client, "root4@example.test")
    r = client.post("/api/v1/platform/organizations", json={
        "name": "Mobiliario Norte", "slug": "mobiliario-norte", "owner_email": "norte@example.test"},
        headers=h_root)
    assert r.status_code == 201, r.json
    token = r.json["invite_url"].split("#token=")[1]
    ok = client.post("/api/v1/invitations/accept", json={"token": token, "password": PASSWORD})
    assert ok.status_code == 200, ok.json
    h_n = {**login(client, "norte@example.test"), "X-Tenant-ID": str(r.json["organization"]["id"])}
    perms = client.get("/api/v1/auth/permissions", headers=h_n).json["permissions"]
    assert {"members.manage", "catalog.manage", "billing.manage"} <= set(perms)


def test_member_role_changes_are_audited(client):
    tenant, h = owner(client, "orgadmin@example.test", "orgadmin")
    with patch(SEND_MEMBERS) as send:
        inv = client.post("/api/v1/invitations", json={"email": "staff@example.test", "role": "staff"}, headers=h)
    token = inv.json["invite_url"].split("#token=")[1]
    client.post("/api/v1/invitations/accept", json={"token": token, "password": PASSWORD})
    member = next(m for m in client.get("/api/v1/memberships", headers=h).json["items"]
                  if m["email"] == "staff@example.test")
    assert client.patch(f"/api/v1/memberships/{member['id']}", json={"role": "viewer"}, headers=h).status_code == 200
    # No se puede asignar el rol de propietario desde la organización.
    assert client.patch(f"/api/v1/memberships/{member['id']}", json={"role": "owner"},
                        headers=h).status_code == 422
    assert {"member.invite", "member.join", "member.role_change"} <= set(audit_actions(client, tenant))


# ----------------------------------------------------------------------------
# Catálogo y cotizaciones mixtas
# ----------------------------------------------------------------------------

def test_categories_managed_from_platform_admin(seeded):
    client = seeded
    owner(client, "root5@example.test", "root5")
    make_owner(client, "root5@example.test")
    tenant, h_t = owner(client, "cat@example.test", "cat-co")
    h_root = login(client, "root5@example.test")
    cats = categories(client, h_root)
    assert len(cats) == 12 and "pirotecnia-y-efectos-especiales" in cats
    new = client.post("/api/v1/platform/catalog/categories", json={"name": "Decoración floral"}, headers=h_root)
    assert new.status_code == 201
    sub = client.post("/api/v1/platform/catalog/categories",
                      json={"name": "Arcos de flores", "parent_id": new.json["category"]["id"]}, headers=h_root)
    assert sub.status_code == 201 and sub.json["category"]["parent_id"] == new.json["category"]["id"]
    # Una organización no administra categorías globales.
    assert client.post("/api/v1/platform/catalog/categories", json={"name": "X"}, headers=h_t).status_code == 403
    # Y puede publicar de inmediato en la subcategoría nueva.
    r = client.post("/api/v1/catalog/offers", json={
        "name": "Arco floral", "category_id": sub.json["category"]["id"], "pricing_mode": "package",
        "unit_price": "4500.00", "fulfillment_type": "manual", "status": "published"}, headers=h_t)
    assert r.status_code == 201
    filtered = client.get(f"/api/v1/catalog/offers?category_id={new.json['category']['id']}", headers=h_t).json
    assert [o["name"] for o in filtered["items"]] == ["Arco floral"]
    assert client.patch(f"/api/v1/platform/catalog/categories/{cats['renta-de-mobiliario']}",
                        json={"is_active": False}, headers=h_root).status_code == 409


def _invite_provider_user(client, h, provider_id, email):
    with patch(SEND_MEMBERS):
        inv = client.post("/api/v1/invitations", json={"email": email, "role": "provider",
                                                       "provider_id": provider_id}, headers=h)
    assert inv.status_code == 201, inv.json
    token = inv.json["invite_url"].split("#token=")[1]
    assert client.post("/api/v1/invitations/accept", json={"token": token, "password": PASSWORD}).status_code == 200
    return {**login(client, email), "X-Tenant-ID": h["X-Tenant-ID"]}


def test_mixed_event_quote_with_furniture_and_services(seeded):
    client = seeded
    tenant, h = owner(client, "mix@example.test", "mix")
    cats = categories(client, h)
    client_id, event_id = new_event(client, h)
    chairs = client.post("/api/v1/inventory/items", json={
        "sku": "SILLA-TIF", "name": "Silla Tiffany", "quantity_total": 200, "unit": "pieza",
        "rental_price": "25.00"}, headers=h)
    assert chairs.status_code == 201, chairs.json
    chairs_id = chairs.json["id"]

    def provider(name):
        return client.post("/api/v1/providers", json={"name": name}, headers=h).json["provider"]["id"]

    banquetes, dj, foto, piro = (provider("Banquetes Sol"), provider("DJ Luna"), provider("Foto Estrella"),
                                 provider("Pirotecnia Norte"))

    def offer(**body):
        r = client.post("/api/v1/catalog/offers", json={"status": "published", **body}, headers=h)
        assert r.status_code == 201, r.json
        return r.json["offer"]

    o_banquet = offer(name="Banquete 3 tiempos", category_id=cats["banquetes-y-catering"], provider_id=banquetes,
                      pricing_mode="per_person", unit_price="350.00", fulfillment_type="manual", min_guests=50)
    o_dj = offer(name="DJ con audio", category_id=cats["dj-y-musica-grabada"], provider_id=dj,
                 pricing_mode="per_hour", unit_price="1500.00", fulfillment_type="schedule", daily_capacity=1,
                 duration_hours="4", coverage="Zona metropolitana", min_notice_days=7)
    o_foto = offer(name="Cobertura fotográfica", category_id=cats["fotografia"], provider_id=foto,
                   pricing_mode="quote", fulfillment_type="manual")
    assert o_foto["unit_price"] is None and o_foto["price_pending"] is True
    o_piro = offer(name="Chisperos fríos", category_id=cats["pirotecnia-y-efectos-especiales"], provider_id=piro,
                   pricing_mode="package", unit_price="2800.00", fulfillment_type="schedule", daily_capacity=3,
                   venue_restrictions="Solo exteriores", required_documents="Permiso municipal")
    assert o_piro["requires_provider_confirmation"] is True

    # El catálogo incluye el mobiliario existente bajo «Renta de mobiliario».
    furniture = client.get(f"/api/v1/catalog/offers?category_id={cats['renta-de-mobiliario']}", headers=h).json
    assert [i["kind"] for i in furniture["items"]] == ["inventory"] and furniture["items"][0]["id"] == chairs_id

    # 80 sillas, banquete para 80, 4 horas de DJ y fotografía bajo cotización, en el mismo evento.
    r = client.post("/api/v1/quotes", json={"client_id": client_id, "event_id": event_id, "items": [
        {"item_type": "inventory", "inventory_item_id": chairs_id, "description": "Silla Tiffany",
         "quantity": "80", "unit_price": "25.00"},
        {"offer_id": o_banquet["id"], "quantity": "80", "guests": 80},
        {"offer_id": o_dj["id"], "quantity": "4", "hours": 4},
        {"offer_id": o_foto["id"], "quantity": "1", "service_notes": "Sesión previa y evento"},
    ]}, headers=h)
    assert r.status_code == 201, r.json
    quote = r.json
    items = {i["description"]: i for i in quote["items"]}
    assert items["Silla Tiffany"]["item_type"] == "inventory" and items["Silla Tiffany"]["price_status"] == "confirmed"
    assert items["Silla Tiffany"]["fulfillment_status"] == "not_required"
    assert items["Banquete 3 tiempos"]["provider_name"] == "Banquetes Sol"
    assert items["Banquete 3 tiempos"]["fulfillment_status"] == "pending_confirmation"
    assert items["DJ con audio"]["fulfillment_status"] == "available"
    assert items["Cobertura fotográfica"]["price_status"] == "pending"
    assert items["Cobertura fotográfica"]["total"] == "0.00"
    # Total confirmado: 80×25 + 80×350 + 4×1500; la fotografía no suma.
    assert Decimal(quote["total"]) == Decimal("36000.00")
    assert quote["pending"]["price_pending"] == 1
    pdf = client.get(f"/api/v1/quotes/{quote['id']}/pdf", headers=h)
    assert pdf.status_code == 200 and pdf.data[:4] == b"%PDF"

    # Cada proveedor ve solo sus partidas y no las cotizaciones completas.
    h_banq = _invite_provider_user(client, h, banquetes, "banquetes@example.test")
    h_foto = _invite_provider_user(client, h, foto, "foto@example.test")
    mine = client.get("/api/v1/provider/items", headers=h_banq).json["items"]
    assert [i["description"] for i in mine] == ["Banquete 3 tiempos"]
    assert mine[0]["event_name"] == "Boda Martínez"
    assert client.get(f"/api/v1/quotes/{quote['id']}", headers=h_banq).status_code == 403
    assert client.get("/api/v1/clients", headers=h_banq).status_code == 403
    assert client.patch(f"/api/v1/provider/items/{items['Cobertura fotográfica']['id']}",
                        json={"unit_price": "1.00"}, headers=h_banq).status_code == 404

    # No se puede aceptar con partidas pendientes.
    assert client.patch(f"/api/v1/quotes/{quote['id']}/status", json={"status": "sent"}, headers=h).status_code == 200
    blocked = client.patch(f"/api/v1/quotes/{quote['id']}/status", json={"status": "accepted"}, headers=h)
    assert blocked.status_code == 409 and blocked.json["details"]["items"] == "pending_items"

    # El fotógrafo registra el importe acordado; cada proveedor confirma su fecha.
    r = client.patch(f"/api/v1/provider/items/{items['Cobertura fotográfica']['id']}",
                     json={"unit_price": "5000.00", "fulfillment_status": "confirmed"}, headers=h_foto)
    assert r.status_code == 200, r.json
    assert client.patch(f"/api/v1/provider/items/{items['Banquete 3 tiempos']['id']}",
                        json={"fulfillment_status": "confirmed"}, headers=h_banq).status_code == 200
    r = client.patch(f"/api/v1/quotes/{quote['id']}/items/{items['DJ con audio']['id']}",
                     json={"fulfillment_status": "confirmed"}, headers=h)
    assert r.status_code == 200
    assert Decimal(r.json["total"]) == Decimal("41000.00") and r.json["pending"]["blocking"] == 0
    accepted = client.patch(f"/api/v1/quotes/{quote['id']}/status", json={"status": "accepted"}, headers=h)
    assert accepted.status_code == 200, accepted.json

    # Agenda: el DJ tiene capacidad 1 por día; otro evento ese mismo día queda no disponible.
    _, other_event = new_event(client, h)
    clients = client.get("/api/v1/clients", headers=h).json["items"]
    other_client = next(c["id"] for c in clients if c["id"] != client_id)
    r2 = client.post("/api/v1/quotes", json={"client_id": other_client, "event_id": other_event,
                                             "items": [{"offer_id": o_dj["id"], "quantity": "3", "hours": 3},
                                                       {"offer_id": o_piro["id"], "quantity": "1"}]}, headers=h)
    assert r2.status_code == 201, r2.json
    by_name = {i["description"]: i for i in r2.json["items"]}
    assert by_name["DJ con audio"]["fulfillment_status"] == "unavailable"
    # Pirotecnia: restricciones, documentos y confirmación del proveedor antes de cerrar.
    piro_item = by_name["Chisperos fríos"]
    assert piro_item["compliance_status"] == "pending"
    assert piro_item["fulfillment_status"] == "pending_confirmation"
    assert piro_item["service_details"]["required_documents"] == "Permiso municipal"
    h_piro = _invite_provider_user(client, h, piro, "piro@example.test")
    assert client.patch(f"/api/v1/provider/items/{piro_item['id']}", json={"compliance_status": "approved"},
                        headers=h_piro).status_code == 403
    r = client.patch(f"/api/v1/quotes/{r2.json['id']}/items/{piro_item['id']}",
                     json={"compliance_status": "approved", "notes": "Permiso recibido"}, headers=h)
    assert r.status_code == 200


def test_furniture_only_quote_flow_unchanged(seeded):
    client = seeded
    tenant, h = owner(client, "legacy@example.test", "legacy")
    client_id, event_id = new_event(client, h)
    item = client.post("/api/v1/inventory/items", json={"sku": "MESA-1", "name": "Mesa redonda",
                                                       "quantity_total": 20, "rental_price": "120.00"},
                       headers=h).json["id"]
    r = client.post("/api/v1/quotes", json={"client_id": client_id, "event_id": event_id, "items": [
        {"item_type": "inventory", "inventory_item_id": item, "description": "Mesa redonda",
         "quantity": "10", "unit_price": "120.00", "tax_rate": "0.16"},
        {"item_type": "custom", "description": "Flete", "quantity": "1", "unit_price": "500.00"},
    ]}, headers=h)
    assert r.status_code == 201, r.json
    assert r.json["total"] == "1892.00"  # 1200×1.16 + 500
    assert all(i["price_status"] == "confirmed" and i["fulfillment_status"] == "not_required"
               for i in r.json["items"])
    for status in ("sent", "accepted"):
        assert client.patch(f"/api/v1/quotes/{r.json['id']}/status", json={"status": status},
                            headers=h).status_code == 200
    assert client.get(f"/api/v1/quotes/{r.json['id']}", headers=h).json["status"] == "accepted"
    # Un viewer sigue consultando cotizaciones y ahora también el catálogo, sin modificarlo.
    with patch(SEND_MEMBERS):
        inv = client.post("/api/v1/invitations", json={"email": "ver@example.test", "role": "viewer"}, headers=h)
    client.post("/api/v1/invitations/accept", json={"token": inv.json["invite_url"].split("#token=")[1],
                                                    "password": PASSWORD})
    h_v = {**login(client, "ver@example.test"), "X-Tenant-ID": str(tenant)}
    assert client.get(f"/api/v1/quotes/{r.json['id']}", headers=h_v).status_code == 200
    assert client.get("/api/v1/catalog/offers", headers=h_v).status_code == 200
    assert client.post("/api/v1/providers", json={"name": "X"}, headers=h_v).status_code == 403


def test_schedule_capacity_counts_local_day_not_utc_day(seeded):
    client = seeded
    _, h = owner(client, "tz@example.test", "tz-co")
    cats = categories(client, h)
    with client.application.app_context():
        from app.models import Tenant
        tenant = db.session.scalar(select(Tenant).where(Tenant.slug == "tz-co"))
        tenant.timezone = "America/Mexico_City"
        db.session.commit()
    dj = client.post("/api/v1/catalog/offers", json={
        "name": "DJ", "category_id": cats["dj-y-musica-grabada"], "pricing_mode": "per_hour", "unit_price": "1000.00",
        "fulfillment_type": "schedule", "daily_capacity": 1, "status": "published"}, headers=h).json["offer"]["id"]
    # 18:00 en Ciudad de México = 00:00 UTC del día siguiente; 10:00 = 16:00 UTC del mismo día.
    c1, e1 = new_event(client, h, "2026-12-12T18:00:00-06:00", "2026-12-12T23:00:00-06:00")
    c2, e2 = new_event(client, h, "2026-12-12T10:00:00-06:00", "2026-12-12T14:00:00-06:00")
    first = client.post("/api/v1/quotes", json={"client_id": c1, "event_id": e1,
                                                "items": [{"offer_id": dj, "quantity": "4", "hours": 4}]}, headers=h)
    assert first.json["items"][0]["fulfillment_status"] == "available"
    second = client.post("/api/v1/quotes", json={"client_id": c2, "event_id": e2,
                                                 "items": [{"offer_id": dj, "quantity": "3", "hours": 3}]}, headers=h)
    assert second.json["items"][0]["fulfillment_status"] == "unavailable"
