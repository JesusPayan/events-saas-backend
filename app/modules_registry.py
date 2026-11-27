"""MOD-01: registro de módulos y capacidades implementados (fuente de verdad en código).

La base de datos guarda la copia administrable (nombre, orden, estado global) y la
configuración de cada organización, pero un módulo o capacidad que no esté aquí no
existe: no se puede crear desde la base de datos ni concede acceso.

Ajustes respecto a la propuesta inicial (ver docs/architecture/MOD-01-MODULAR-ARCHITECTURE.md):
- Reservas, movimientos, incidencias y reabastecimiento son capacidades del módulo
  INVENTORY (comparten endpoints y datos); no son módulos separados.
- EXPORTS forma parte de REPORTS; SERVICE_AVAILABILITY es una capacidad del catálogo
  (agenda y capacidad diaria de las ofertas).
- AUDIT es del panel de plataforma, no un módulo de organización.
"""
from dataclasses import dataclass, field

AVAILABLE = "available"
EXPERIMENTAL = "experimental"
COMING_SOON = "coming_soon"


@dataclass(frozen=True)
class ModuleDef:
    code: str
    name: str
    description: str
    icon: str
    category: str
    sort_order: int
    essential: bool = False
    depends_on: tuple = ()
    capabilities: tuple = ()
    status: str = AVAILABLE
    feature_flag: str | None = None
    min_version: str = "1.3.0"
    # Rutas del frontend que pertenecen al módulo (menú y guards).
    routes: tuple = field(default=())

    @property
    def configurable(self):
        return not self.essential and self.status == AVAILABLE


MODULES = (
    ModuleDef("CORE_DASHBOARD", "Panel de control", "Resumen de la operación de la empresa.", "dashboard",
              "core", 10, essential=True, capabilities=("dashboard.view",), routes=("/dashboard",)),
    ModuleDef("CORE_CLIENTS", "Clientes", "Cartera de clientes.", "users", "core", 20, essential=True,
              capabilities=("clients.manage",), routes=("/clients",)),
    ModuleDef("CORE_EVENTS", "Eventos", "Registro y seguimiento de eventos.", "calendar-days", "core", 30,
              essential=True, capabilities=("events.manage",), routes=("/events",)),
    ModuleDef("CORE_CALENDAR", "Calendario", "Vista mensual de eventos.", "calendar", "core", 40, essential=True,
              capabilities=("calendar.view",), routes=("/events/calendar",)),
    ModuleDef("COMMERCIAL_QUOTES", "Cotizaciones", "Cotizaciones con conceptos, descuentos, impuestos y PDF.",
              "file-text", "commercial", 50, essential=True,
              capabilities=("quotes.manage", "quotes.pdf", "quotes.pending_prices"), routes=("/quotes",)),
    ModuleDef("COMMERCIAL_CONTRACTS", "Contratos", "Contratos, firma electrónica y configuración de comprobantes.",
              "file-signature", "commercial", 60,
              capabilities=("contracts.manage", "contracts.e_signature"),
              routes=("/contracts", "/company/receipt-settings")),
    ModuleDef("COMMERCIAL_PAYMENTS", "Pagos y anticipos", "Pagos de contratos y comprobantes no fiscales.",
              "wallet", "commercial", 70, depends_on=("COMMERCIAL_CONTRACTS",),
              capabilities=("payments.manage", "payments.receipts")),
    ModuleDef("COMMERCIAL_CATALOG", "Catálogo de servicios",
              "Ofertas por unidad, persona, hora, paquete o evento, con agenda y confirmación.",
              "store", "commercial", 80,
              capabilities=("catalog.offers", "catalog.availability", "catalog.quote_items"), routes=("/catalog",)),
    ModuleDef("SUPPLIERS", "Proveedores internos", "Subcontratistas con portal propio para confirmar sus partidas.",
              "truck", "commercial", 90, depends_on=("COMMERCIAL_CATALOG",),
              capabilities=("suppliers.manage", "suppliers.portal"), routes=("/providers", "/provider/items")),
    ModuleDef("ORGANIZATION_NETWORK", "Red de organizaciones",
              "Catálogo compartido y solicitudes entre empresas.", "network", "commercial", 100,
              depends_on=("COMMERCIAL_CATALOG",),
              capabilities=("network.browse", "network.share", "network.requests"), routes=("/network/requests",)),
    ModuleDef("INVENTORY", "Inventario",
              "Artículos, existencias, reservas, movimientos, incidencias, cargos y reabastecimiento.",
              "package", "operations", 110,
              capabilities=("inventory.items", "inventory.reservations", "inventory.movements",
                            "inventory.incidents", "inventory.charges", "inventory.replenishment",
                            "inventory.capacity_alerts"), routes=("/inventory",)),
    ModuleDef("LOGISTICS", "Logística", "Órdenes de preparación, despacho y entrega.", "route", "operations", 120,
              depends_on=("INVENTORY",), capabilities=("logistics.orders",), routes=("/logistics",)),
    ModuleDef("REPORTS", "Reportes", "Reportes de disponibilidad y movimientos, exportables a CSV y Excel.",
              "chart", "operations", 130, depends_on=("INVENTORY",),
              capabilities=("reports.inventory", "reports.exports"), routes=("/inventory/reports",)),
    ModuleDef("TEAM_MANAGEMENT", "Equipo", "Miembros, roles, invitaciones y accesos temporales.", "users-cog",
              "administration", 140, essential=True, capabilities=("team.manage", "team.access_grants"),
              routes=("/members",)),
    ModuleDef("SUBSCRIPTION_MANAGEMENT", "Suscripción", "Planes, pagos con Mercado Pago y límites del plan.",
              "credit-card", "administration", 150, essential=True, capabilities=("subscription.manage",),
              routes=("/billing",)),
    # Futuro: visible como «próximamente», nunca habilitable mientras no exista.
    ModuleDef("SPACE_BOOKING", "Reservación de espacios", "Agenda especializada para salones y jardines.",
              "building", "operations", 160, status=COMING_SOON, capabilities=()),
)

MODULES_BY_CODE = {m.code: m for m in MODULES}
CAPABILITY_MODULE = {cap: m.code for m in MODULES for cap in m.capabilities}
ESSENTIAL_MODULES = frozenset(m.code for m in MODULES if m.essential)
OPTIONAL_MODULES = frozenset(m.code for m in MODULES if m.configurable)

# Módulos comunes para una organización nueva mientras completa el onboarding (8.1).
DEFAULT_NEW_TENANT_MODULES = frozenset({"COMMERCIAL_CONTRACTS", "COMMERCIAL_PAYMENTS", "COMMERCIAL_CATALOG"})

# Endpoints → módulo. Primero el endpoint exacto; si no, el blueprint.
BLUEPRINT_MODULES = {
    "clients": "CORE_CLIENTS",
    "events": "CORE_EVENTS",
    "quotes": "COMMERCIAL_QUOTES",
    "contracts": "COMMERCIAL_CONTRACTS",
    "contract_documents": "COMMERCIAL_CONTRACTS",
    "contract_signature_admin": "COMMERCIAL_CONTRACTS",
    "contract_signature_receipts": "COMMERCIAL_CONTRACTS",
    "signature_delivery": "COMMERCIAL_CONTRACTS",
    "company_receipts": "COMMERCIAL_CONTRACTS",
    "contract_payments": "COMMERCIAL_PAYMENTS",
    "payment_receipts": "COMMERCIAL_PAYMENTS",
    "inventory": "INVENTORY",
    "inventory_capacity_alert_events": "INVENTORY",
    "inventory_charges": "INVENTORY",
    "inventory_incidents": "INVENTORY",
    "inventory_movements": "INVENTORY",
    "inventory_operations": "INVENTORY",
    "inventory_replenishments": "INVENTORY",
    "inventory_reservations": "INVENTORY",
    "logistics": "LOGISTICS",
    "catalog": "COMMERCIAL_CATALOG",
    "members": "TEAM_MANAGEMENT",
    "billing": "SUBSCRIPTION_MANAGEMENT",
    "mercadopago_billing": "SUBSCRIPTION_MANAGEMENT",
}
ENDPOINT_MODULES = {
    "catalog.list_providers": "SUPPLIERS",
    "catalog.create_provider": "SUPPLIERS",
    "catalog.update_provider": "SUPPLIERS",
    "catalog.my_provider_items": "SUPPLIERS",
    "catalog.update_my_provider_item": "SUPPLIERS",
    "catalog.network_catalog": "ORGANIZATION_NETWORK",
    "catalog.list_network_requests": "ORGANIZATION_NETWORK",
    "catalog.respond_network_request": "ORGANIZATION_NETWORK",
    "inventory.inventory_movement_report_export": "REPORTS",
    "inventory.inventory_availability_report_export": "REPORTS",
    "inventory.inventory_availability_report": "REPORTS",
    "inventory.inventory_movement_report": "REPORTS",
    "inventory.inventory_movement_report_excel_export": "REPORTS",
    "inventory.inventory_availability_report_excel_export": "REPORTS",
    "platform.list_access_grants": "TEAM_MANAGEMENT",
    "platform.create_access_grant": "TEAM_MANAGEMENT",
    "platform.revoke_access_grant": "TEAM_MANAGEMENT",
}


def module_for_endpoint(endpoint):
    if not endpoint:
        return None
    if endpoint in ENDPOINT_MODULES:
        return ENDPOINT_MODULES[endpoint]
    return BLUEPRINT_MODULES.get(endpoint.split(".", 1)[0])


def dependency_closure(codes):
    """Agrega las dependencias (transitivas) de los módulos indicados."""
    result, stack = set(), list(codes)
    while stack:
        code = stack.pop()
        if code in result:
            continue
        module = MODULES_BY_CODE.get(code)
        if module is None:
            raise KeyError(code)
        result.add(code)
        stack.extend(module.depends_on)
    return result


def dependents_of(code):
    """Módulos que dependen (directa o indirectamente) de ``code``."""
    found, changed = set(), True
    while changed:
        changed = False
        for m in MODULES:
            if m.code not in found and (code in m.depends_on or found.intersection(m.depends_on)):
                found.add(m.code)
                changed = True
    return found


def find_cycle(modules=MODULES):
    """Devuelve un ciclo de dependencias si existe (lista de códigos), o None."""
    graph = {m.code: m.depends_on for m in modules}
    state = {}

    def visit(node, path):
        state[node] = "visiting"
        for dep in graph.get(node, ()):
            if state.get(dep) == "visiting":
                return path + [node, dep]
            if dep not in state:
                cycle = visit(dep, path + [node])
                if cycle:
                    return cycle
        state[node] = "done"
        return None

    for code in graph:
        if code not in state:
            cycle = visit(code, [])
            if cycle:
                return cycle
    return None


def validate_registry(modules=MODULES):
    codes = [m.code for m in modules]
    if len(codes) != len(set(codes)):
        raise ValueError("Códigos de módulo duplicados")
    known = set(codes)
    for m in modules:
        missing = set(m.depends_on) - known
        if missing:
            raise ValueError(f"{m.code} depende de módulos inexistentes: {sorted(missing)}")
        if m.essential and m.depends_on and not set(m.depends_on) <= {x.code for x in modules if x.essential}:
            raise ValueError(f"El módulo esencial {m.code} no puede depender de módulos opcionales")
    caps = [c for m in modules for c in m.capabilities]
    if len(caps) != len(set(caps)):
        raise ValueError("Capacidades duplicadas entre módulos")
    cycle = find_cycle(modules)
    if cycle:
        raise ValueError(f"Dependencia circular: {' → '.join(cycle)}")


validate_registry()
