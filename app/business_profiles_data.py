"""MOD-01: datos semilla de giros comerciales y sus plantillas de módulos (versión 1).

Solo datos (sin dependencias de base de datos) para que la migración, el seed y las
pruebas usen exactamente la misma definición. Los módulos esenciales siempre están
activos y no se listan en las plantillas.

Matriz completa y justificación: docs/product/BUSINESS-TYPE-MODULE-MATRIX.md
"""

CONTRACTS = ("COMMERCIAL_CONTRACTS", "COMMERCIAL_PAYMENTS")
SERVICES = CONTRACTS + ("COMMERCIAL_CATALOG", "ORGANIZATION_NETWORK")
RENTAL = SERVICES + ("INVENTORY", "LOGISTICS")

# (código, nombre, descripción, icono, orden, módulos recomendados, admite descripción libre)
BUSINESS_TYPES = (
    ("EVENT_PLANNER", "Organización de eventos",
     "Coordinas eventos completos con proveedores propios y de la red.", "sparkles", 10,
     CONTRACTS + ("COMMERCIAL_CATALOG", "SUPPLIERS", "ORGANIZATION_NETWORK"), False),
    ("FURNITURE_RENTAL", "Renta de mobiliario",
     "Rentas sillas, mesas, carpas y equipo con control de inventario y entregas.", "armchair", 20,
     RENTAL + ("REPORTS",), False),
    ("EVENT_VENUE", "Salones y jardines de eventos",
     "Rentas espacios para eventos y coordinas servicios incluidos.", "building", 30,
     CONTRACTS + ("COMMERCIAL_CATALOG", "SUPPLIERS"), False),
    ("CATERING", "Banquetes y catering",
     "Ofreces alimentos por persona o por paquete, con montaje y equipo.", "utensils", 40,
     CONTRACTS + ("COMMERCIAL_CATALOG", "SUPPLIERS", "INVENTORY", "LOGISTICS"), False),
    ("COCKTAIL_SERVICE", "Coctelería y bebidas", "Barras de bebidas y mixología para eventos.", "martini", 50,
     SERVICES, False),
    ("BAKERY_DESSERTS", "Repostería y mesas de postres", "Pasteles, postres y mesas dulces.", "cake", 60,
     SERVICES, False),
    ("SNACKS_SERVICE", "Botanas y mesas de snacks", "Mesas de botanas y snacks para eventos.", "popcorn", 70,
     SERVICES, False),
    ("CHEESE_TABLES", "Mesas de quesos y charcutería", "Tablas y barras de quesos y carnes frías.", "cheese", 80,
     SERVICES, False),
    ("PHOTOGRAPHY", "Fotografía", "Cobertura fotográfica de eventos por paquete u hora.", "camera", 90,
     SERVICES, False),
    ("VIDEOGRAPHY", "Video", "Grabación y edición de video de eventos.", "video", 100, SERVICES, False),
    ("LIVE_MUSIC", "Música en vivo", "Grupos, mariachis y músicos por hora o por evento.", "music", 110,
     SERVICES, False),
    ("DJ_SERVICE", "DJ y entretenimiento", "DJ, animación y entretenimiento por hora o por evento.", "disc", 120,
     SERVICES, False),
    ("AUDIO_LIGHTING", "Audio e iluminación", "Renta y operación de audio, iluminación y pantallas.", "speaker",
     130, RENTAL + ("SUPPLIERS",), False),
    ("EVENT_DECORATION", "Decoración de eventos", "Decoración, ambientación y montaje.", "palette", 140,
     RENTAL + ("SUPPLIERS",), False),
    ("FLORIST", "Floristería", "Arreglos florales y decoración con flores.", "flower", 150,
     RENTAL + ("SUPPLIERS",), False),
    ("PYROTECHNICS", "Pirotecnia", "Espectáculos de pirotecnia y efectos especiales con permisos.", "flame", 160,
     SERVICES, False),
    ("MULTI_SERVICE", "Empresa multiservicios",
     "Ofreces varios servicios; combina este giro con los que correspondan.", "layers", 170,
     CONTRACTS + ("COMMERCIAL_CATALOG", "SUPPLIERS", "ORGANIZATION_NETWORK"), False),
    ("OTHER", "Otro giro comercial", "Describe tu actividad; podrás ajustar los módulos después.", "dots", 180,
     CONTRACTS + ("COMMERCIAL_CATALOG",), True),
)

# Perfil interno de compatibilidad para organizaciones creadas antes de v1.3.0: conserva
# todos los módulos que ya tenían. No se muestra como giro comercial.
LEGACY_CODE = "LEGACY_COMPATIBILITY"
LEGACY_MODULES = ("COMMERCIAL_CONTRACTS", "COMMERCIAL_PAYMENTS", "COMMERCIAL_CATALOG", "SUPPLIERS",
                  "ORGANIZATION_NETWORK", "INVENTORY", "LOGISTICS", "REPORTS")

FEATURE_FLAGS = (
    ("modules.enforcement", True,
     "Aplica en el servidor los módulos deshabilitados y los incluidos en el plan."),
)
