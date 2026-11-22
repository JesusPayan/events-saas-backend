
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Barrier

import requests


def reconcile(worker, barrier, url, token, tenant_id):
    try:
        barrier.wait(timeout=10)

        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Tenant-ID": str(tenant_id),
                "Content-Type": "application/json",
            },
            json={"accept_deficit": True},
            timeout=45,
        )

        try:
            body = response.json()
        except ValueError:
            body = response.text[:1500]

        return {
            "worker": worker,
            "status": response.status_code,
            "body": body,
        }

    except Exception as exc:
        return {
            "worker": worker,
            "status": "ERROR",
            "error": str(exc),
        }


def main():
    base_url = os.getenv(
        "API_BASE_URL",
        "http://127.0.0.1:5001/api/v1",
    ).rstrip("/")

    token = os.getenv("TEST_ACCESS_TOKEN")
    tenant_id = os.getenv("TEST_TENANT_ID")
    incident_id = os.getenv("TEST_INCIDENT_ID")

    if not all([token, tenant_id, incident_id]):
        print(
            "ERROR: Debes configurar "
            "TEST_ACCESS_TOKEN, TEST_TENANT_ID "
            "y TEST_INCIDENT_ID."
        )
        return 1

    url = (
        f"{base_url}/inventory/incidents/"
        f"{incident_id}/reconcile"
    )

    print("=== PRUEBA MANUAL DE CONCURRENCIA ===")
    print(f"URL: {url}")
    print(f"Tenant: {tenant_id}")
    print(f"Incidencia: {incident_id}")

    barrier = Barrier(2)
    results = []

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                reconcile,
                worker,
                barrier,
                url,
                token,
                tenant_id,
            )
            for worker in (1, 2)
        ]

        for future in as_completed(futures):
            result = future.result()
            results.append(result)

            print(
                f"Worker {result['worker']}: "
                f"HTTP {result['status']}"
            )
            print(result)

    statuses = sorted(
        result["status"]
        for result in results
        if isinstance(result["status"], int)
    )

    if statuses == [200, 409]:
        print("PASS: concurrencia controlada.")
        return 0

    print("FAIL: resultado inesperado.")
    print("Verifica la base de datos.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
