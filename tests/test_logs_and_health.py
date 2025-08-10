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


def test_health_and_ping():
    h = requests.get(f"{BASE_URL}/observability/health")
    p = requests.get(f"{BASE_URL}/observability/ping")
    assert h.status_code == 200 and p.status_code == 200
    assert h.json().get("status") == "ok" and p.json().get("pong") is True


def test_run_logs_endpoint():
    # prepare approved work item
    pr = requests.post(f"{BASE_URL}/projects/", json={"name": "logs-demo", "description": ""}).json()
    wi = requests.post(
        f"{BASE_URL}/work-items/",
        json={"project_id": pr["id"], "title": "Log run", "description": ""},
    ).json()
    ar = requests.post(f"{BASE_URL}/work-items/{wi['id']}/approvals").json()
    requests.post(f"{BASE_URL}/work-items/approvals/{ar['id']}/approve")
    run = requests.post(f"{BASE_URL}/work-items/{wi['id']}/start").json()

    logs = requests.get(f"{BASE_URL}/work-items/runs/{run['id']}/logs")
    assert logs.status_code == 200
    assert "Starting run" in logs.text

