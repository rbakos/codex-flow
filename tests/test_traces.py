import subprocess
import time
import os
import requests


BASE_URL = os.getenv("ORCH_URL", "http://localhost:18080")


def wait_for_service(url: str, timeout: int = 60):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(url)
            if r.status_code in (200, 404):
                return True
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("Service did not become ready in time")


def setup_module(module):
    subprocess.run(["docker", "compose", "up", "-d", "--build"], check=True)
    wait_for_service(f"{BASE_URL}/openapi.json")


def teardown_module(module):
    subprocess.run(["docker", "compose", "down", "-v"], check=True)


def test_traces_list_stub():
    # ensure at least one run exists
    p = requests.post(f"{BASE_URL}/projects/", json={"name": "trace-demo", "description": ""}).json()
    wi = requests.post(
        f"{BASE_URL}/work-items/",
        json={"project_id": p["id"], "title": "Trace run", "description": ""},
    ).json()
    ar = requests.post(f"{BASE_URL}/work-items/{wi['id']}/approvals").json()
    requests.post(f"{BASE_URL}/work-items/approvals/{ar['id']}/approve")
    run = requests.post(f"{BASE_URL}/work-items/{wi['id']}/start").json()

    r = requests.get(f"{BASE_URL}/observability/traces")
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    assert any(item.get("run_id") == run["id"] and item.get("trace_id") for item in items)

