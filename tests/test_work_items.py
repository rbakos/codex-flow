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


def test_work_item_run_flow():
    # Create project
    r = requests.post(f"{BASE_URL}/projects/", json={"name": "wi-demo", "description": "work item demo"})
    assert r.status_code == 201
    project_id = r.json()["id"]

    # Create work item
    wi = requests.post(
        f"{BASE_URL}/work-items/",
        json={"project_id": project_id, "title": "Implement scheduler stub", "description": "MVP"},
    )
    assert wi.status_code == 201, wi.text
    wi_id = wi.json()["id"]

    # Request and approve before starting run
    ar = requests.post(f"{BASE_URL}/work-items/{wi_id}/approvals", json={"reason": "dev run"})
    assert ar.status_code == 201
    approval_id = ar.json()["id"]
    approved = requests.post(f"{BASE_URL}/work-items/approvals/{approval_id}/approve")
    assert approved.status_code == 200

    # Start run (agent stub)
    run = requests.post(f"{BASE_URL}/work-items/{wi_id}/start")
    assert run.status_code == 200, run.text
    run_id = run.json()["id"]
    assert run.json()["status"] == "running"

    # Complete run successfully
    done = requests.post(f"{BASE_URL}/work-items/runs/{run_id}/complete", params={"success": True})
    assert done.status_code == 200
    assert done.json()["status"] == "succeeded"
