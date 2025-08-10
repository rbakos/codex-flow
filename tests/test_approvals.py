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


def test_approval_required_then_start_run():
    # Create project
    r = requests.post(f"{BASE_URL}/projects/", json={"name": "approve-demo", "description": "demo"})
    project_id = r.json()["id"]

    # Create work item
    wi = requests.post(
        f"{BASE_URL}/work-items/",
        json={"project_id": project_id, "title": "Deploy to prod", "description": "requires approval"},
    )
    wi_id = wi.json()["id"]

    # Attempt to start run without approval should fail
    start = requests.post(f"{BASE_URL}/work-items/{wi_id}/start")
    assert start.status_code == 403

    # Request approval and approve it
    ar = requests.post(f"{BASE_URL}/work-items/{wi_id}/approvals", json={"reason": "prod deploy"})
    assert ar.status_code == 201
    approval_id = ar.json()["id"]

    approved = requests.post(f"{BASE_URL}/work-items/approvals/{approval_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    # Start run should now succeed
    run = requests.post(f"{BASE_URL}/work-items/{wi_id}/start")
    assert run.status_code == 200
    assert run.json()["status"] == "running"
