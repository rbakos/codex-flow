import os
import time
import subprocess
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


def test_project_vision_requirements_flow():
    # Create project
    r = requests.post(f"{BASE_URL}/projects/", json={"name": "demo", "description": "test"})
    assert r.status_code == 201, r.text
    project = r.json()

    # Submit vision
    v = requests.post(
        f"{BASE_URL}/projects/{project['id']}/vision", json={"content": "Build an orchestrator MVP"}
    )
    assert v.status_code == 201, v.text

    # Propose requirements
    pr = requests.post(f"{BASE_URL}/projects/{project['id']}/requirements/propose")
    assert pr.status_code == 200, pr.text
    draft = pr.json()
    assert draft["status"] == "proposed"
    assert "Proposed Requirements" in draft["draft"]

    # Approve requirements
    ap = requests.post(f"{BASE_URL}/projects/{project['id']}/requirements/approve")
    assert ap.status_code == 200, ap.text
    assert ap.json()["status"] == "approved"
