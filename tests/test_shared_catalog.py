"""NET-01: catálogo compartido entre organizaciones.

Reglas del negocio:
- Solo se comparten las ofertas que cada organización marca (y publica).
- La organización que presta el servicio ve los datos del evento y del cliente.
- El precio del proveedor es el costo; quien cotiza fija su precio de venta.
"""
from decimal import Decimal

from sqlalchemy import select

from app.extensions import db
from app.models.platform import AuditEvent
from tests.test_identity import client  # noqa: F401
from tests.test_roles_catalog import (  # noqa: F401
    bootstrap_owner, categories, login, new_event, owner, seeded,
)


def _offer(client, h, **body):
    r = client.post("/api/v1/catalog/offers", json={"status": "published", **body}, headers=h)
    assert r.status_code == 201, r.json
    return r.json["offer"]


def _network(client, h, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    r = client.get(f"/api/v1/catalog/network?{query}", headers=h)
    assert r.status_code == 200, r.json
    return r.json["items"]


def test_only_marked_published_offers_are_shared(seeded):
    client = seeded
    tenant_a, h_a = owner(client, "red-a@example.test", "red-a")
    _, h_b = owner(client, "red-b@example.test", "red-b")
    cats = categories(client, h_a)
    private = _offer(client, h_a, name="Banquete privado", category_id=cats["banquetes-y-catering"],
                     pricing_mode="per_person", unit_price="300.00", fulfillment_type="manual")
    shared = _offer(client, h_a, name="Banquete de la red", category_id=cats["banquetes-y-catering"],
                    pricing_mode="per_person", unit_price="350.00", fulfillment_type="manual", shared=True)
    draft = _offer(client, h_a, name="Borrador compartido", category_id=cats["video"], pricing_mode="quote",
                   fulfillment_type="manual", shared=True, status="draft")
    visible = _network(client, h_b)
    assert [o["id"] for o in visible] == [shared["id"]]
    assert visible[0]["supplier_name"] == "Empresa red-a" and visible[0]["cost_unit_price"] == "350.00"
    assert visible[0]["provider_name"] is None  # los proveedores internos de A no se exponen
    assert private["id"] not in [o["id"] for o in visible] and draft["id"] not in [o["id"] for o in visible]
    # Una organización no ve sus propias ofertas en la red.
    assert _network(client, h_a) == []
    # Filtro por categoría.
    assert _network(client, h_b, category_id=cats["video"]) == []
    # Dejar de compartir la retira de la red.
    client.patch(f"/api/v1/catalog/offers/{shared['id']}", json={"shared": False}, headers=h_a)
    assert _network(client, h_b) == []
    # Una organización suspendida desaparece de la red.
    client.patch(f"/api/v1/catalog/offers/{shared['id']}", json={"shared": True}, headers=h_a)
    owner(client, "red-root@example.test", "red-root")
    with client.application.app_context():
        bootstrap_owner("red-root@example.test")
    h_root = login(client, "red-root@example.test")
    client.patch(f"/api/v1/platform/organizations/{tenant_a}/status", json={"status": "suspended"}, headers=h_root)
    assert _network(client, h_b) == []


def test_network_item_cost_sale_price_and_supplier_view(seeded):
    client = seeded
    tenant_a, h_a = owner(client, "sup-a@example.test", "sup-a")
    tenant_b, h_b = owner(client, "req-b@example.test", "req-b")
    _, h_c = owner(client, "other-c@example.test", "other-c")
    cats = categories(client, h_a)
    banquet = _offer(client, h_a, name="Banquete 3 tiempos", category_id=cats["banquetes-y-catering"],
                     pricing_mode="per_person", unit_price="350.00", fulfillment_type="manual", shared=True)
    photo = _offer(client, h_a, name="Fotografía", category_id=cats["fotografia"], pricing_mode="quote",
                   fulfillment_type="manual", shared=True)
    # B no puede usar su propia oferta como «de la red».
    own = _offer(client, h_b, name="Propia", category_id=cats["video"], pricing_mode="per_event",
                 unit_price="100.00", fulfillment_type="manual", shared=True)

    c = client.post("/api/v1/clients", json={"first_name": "Ana", "last_name": "López", "email": "ana@cliente.test",
                                             "phone": "5550001111"}, headers=h_b).json["id"]
    e = client.post("/api/v1/events", json={"client_id": c, "event_type": "social", "name": "Boda López",
                                            "starts_at": "2026-12-12T18:00:00-06:00",
                                            "ends_at": "2026-12-13T02:00:00-06:00", "location": "Jardín Real",
                                            "estimated_guests": 80}, headers=h_b).json["id"]
    bad = client.post("/api/v1/quotes", json={"client_id": c, "event_id": e, "items": [
        {"network_offer_id": own["id"], "quantity": "1"}]}, headers=h_b)
    assert bad.status_code == 404

    r = client.post("/api/v1/quotes", json={"client_id": c, "event_id": e, "items": [
        {"network_offer_id": banquet["id"], "quantity": "80", "guests": 80, "unit_price": "420.00"},
        {"network_offer_id": photo["id"], "quantity": "1", "service_notes": "Cobertura completa"},
    ]}, headers=h_b)
    assert r.status_code == 201, r.json
    quote = r.json
    items = {i["network_offer_id"]: i for i in quote["items"]}
    b_item, p_item = items[banquet["id"]], items[photo["id"]]
    assert b_item["supplier_name"] == "Empresa sup-a" and b_item["cost_unit_price"] == "350.00"
    assert b_item["unit_price"] == "420.00" and b_item["total"] == "33600.00"  # precio de venta, no el costo
    assert b_item["fulfillment_status"] == "pending_confirmation"
    assert p_item["cost_status"] == "pending" and p_item["price_status"] == "pending"
    assert Decimal(quote["total"]) == Decimal("33600.00")
    assert quote["pending"]["cost_pending"] == 1

    # A ve sus solicitudes con datos del evento y del cliente, pero nunca el precio de venta de B.
    requests = client.get("/api/v1/network/requests", headers=h_a).json["items"]
    assert {i["id"] for i in requests} == {b_item["id"], p_item["id"]}
    req = next(i for i in requests if i["id"] == b_item["id"])
    assert req["requester_name"] == "Empresa req-b" and req["event_name"] == "Boda López"
    assert req["event_location"] == "Jardín Real" and req["estimated_guests"] == 80
    assert req["client"]["name"] == "Ana López" and req["client"]["email"] == "ana@cliente.test"
    assert req["cost_total"] == "28000.00"
    assert "unit_price" not in req and "total" not in req
    # A no puede abrir la cotización de B ni sus clientes.
    forged = {**h_a, "X-Tenant-ID": str(tenant_b)}
    assert client.get(f"/api/v1/quotes/{quote['id']}", headers=forged).status_code == 403
    assert client.get(f"/api/v1/quotes/{quote['id']}", headers=h_a).status_code == 404
    # Una tercera organización no ve ni responde solicitudes ajenas.
    assert client.get("/api/v1/network/requests", headers=h_c).json["items"] == []
    assert client.patch(f"/api/v1/network/requests/{b_item['id']}", json={"fulfillment_status": "confirmed"},
                        headers=h_c).status_code == 404

    # Solo el proveedor confirma la fecha; quien cotiza no puede hacerlo por él.
    denied = client.patch(f"/api/v1/quotes/{quote['id']}/items/{b_item['id']}",
                          json={"fulfillment_status": "confirmed"}, headers=h_b)
    assert denied.status_code == 403 and denied.json["details"]["fulfillment_status"] == "supplier_only"
    assert client.patch(f"/api/v1/quotes/{quote['id']}/status", json={"status": "sent"}, headers=h_b).status_code == 200
    blocked = client.patch(f"/api/v1/quotes/{quote['id']}/status", json={"status": "accepted"}, headers=h_b)
    assert blocked.status_code == 409

    ok = client.patch(f"/api/v1/network/requests/{b_item['id']}", json={"fulfillment_status": "confirmed"},
                      headers=h_a)
    assert ok.status_code == 200 and ok.json["item"]["fulfillment_status"] == "confirmed"
    ok = client.patch(f"/api/v1/network/requests/{p_item['id']}",
                      json={"cost_unit_price": "4000.00", "fulfillment_status": "confirmed",
                            "notes": "Incluye álbum"}, headers=h_a)
    assert ok.status_code == 200 and ok.json["item"]["cost_status"] == "confirmed"
    # Con el costo confirmado, B fija su precio de venta (margen) y ya puede aceptar.
    r = client.patch(f"/api/v1/quotes/{quote['id']}/items/{p_item['id']}", json={"unit_price": "5000.00"},
                     headers=h_b)
    assert r.status_code == 200 and Decimal(r.json["total"]) == Decimal("38600.00")
    assert r.json["pending"]["blocking"] == 0
    assert client.patch(f"/api/v1/quotes/{quote['id']}/status", json={"status": "accepted"},
                        headers=h_b).status_code == 200
    # Cotización cerrada: el proveedor ya no puede cambiar su respuesta.
    assert client.patch(f"/api/v1/network/requests/{p_item['id']}", json={"cost_unit_price": "1.00"},
                        headers=h_a).status_code == 409

    with client.application.app_context():
        actions = {(a.action, a.tenant_id) for a in db.session.scalars(select(AuditEvent)).all()}
    assert ("network_request.create", tenant_b) in actions
    assert ("network_request.respond", tenant_a) in actions


def test_supplier_viewer_reads_requests_but_cannot_respond(seeded):
    """Lectura con catalog.read; responder exige catalog.manage."""
    client = seeded
    tenant_a, h_a = owner(client, "sv-a@example.test", "sv-a")
    from unittest.mock import patch
    with patch("app.api.members.send_email"):
        inv = client.post("/api/v1/invitations", json={"email": "sv-viewer@example.test", "role": "viewer"},
                          headers=h_a)
    client.post("/api/v1/invitations/accept", json={"token": inv.json["invite_url"].split("#token=")[1],
                                                    "password": "a-very-long-password"})
    h_v = {**login(client, "sv-viewer@example.test"), "X-Tenant-ID": str(tenant_a)}
    assert client.get("/api/v1/network/requests", headers=h_v).status_code == 200
    assert client.patch("/api/v1/network/requests/1", json={"fulfillment_status": "confirmed"},
                        headers=h_v).status_code == 403
