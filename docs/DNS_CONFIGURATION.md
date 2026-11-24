# Configuración DNS — easiacc.com

El dominio `easiacc.com` está registrado en **Namecheap** y su DNS se administra en **Cloudflare** (plan
gratuito). En Namecheap solo se cambian los servidores de nombres (*Custom DNS*) a los que indica Cloudflare;
el registro y la renovación siguen en Namecheap.

## Distribución de hosts

| Host | Uso | Servidor |
|---|---|---|
| `easiacc.com` | Landing comercial | Producción (mismo frontend) |
| `www.easiacc.com` | Redirección 301 a `easiacc.com` | Producción (Caddy) |
| `app.easiacc.com` | Aplicación (y API en `app.easiacc.com/api`, mismo origen, sin CORS) | Producción |
| `staging.easiacc.com` | Pruebas con credenciales de prueba de Mercado Pago | Staging |

No se usa `api.easiacc.com` ni `admin.easiacc.com`: la API se sirve en el mismo origen y el panel global
está dentro de la aplicación, protegido por `BILLING_OPERATOR_USER_IDS`.

## Registros en Cloudflare (*DNS → Records*)

| Tipo | Nombre | Contenido | Proxy |
|---|---|---|---|
| A | `@` | IP pública del Linode de producción | DNS only (nube gris) |
| A | `app` | IP pública del Linode de producción | DNS only |
| CNAME | `www` | `easiacc.com` | DNS only |
| A | `staging` | IP pública del Linode de staging | DNS only |

Con **DNS only**, Caddy obtiene los certificados HTTPS de Let's Encrypt automáticamente. Más adelante puedes
activar el proxy de Cloudflare (nube naranja) con *SSL/TLS → Full (strict)*.

En el servidor, `deploy/env/stack.env`:

```
DOMAIN=app.easiacc.com, easiacc.com, www.easiacc.com      # producción
DOMAIN=staging.easiacc.com                                # staging
```

## Correo transaccional

Al contratar el proveedor de correo (por ejemplo Brevo o Resend), agrega en Cloudflare los registros que
indique: **SPF** (TXT), **DKIM** (TXT o CNAME) y **DMARC** (`TXT _dmarc` con `v=DMARC1; p=none; rua=mailto:...`
al inicio). Sin ellos, las invitaciones y los correos de recuperación pueden llegar a spam.

## Mercado Pago

Tras el despliegue, configura en la aplicación de Mercado Pago:
- Webhook: `https://app.easiacc.com/api/v1/billing/mercadopago/webhook`
- `MP_BACK_URL=https://app.easiacc.com/billing/return`

## Verificación

```bash
dig +short easiacc.com app.easiacc.com www.easiacc.com
```

```bash
curl -sI https://www.easiacc.com | grep -i location
```

```bash
curl -s https://app.easiacc.com/api/v1/ready
```
