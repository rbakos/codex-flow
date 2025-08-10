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


def test_scheduler_with_dependency_and_approvals():
    # project
    r = requests.post(f"{BASE_URL}/projects/", json={"name": "sched-demo", "description": "demo"})
    pid = r.json()["id"]

    # work items A then B depends on A
    a = requests.post(f"{BASE_URL}/work-items/", json={"project_id": pid, "title": "A", "description": ""}).json()
    b = requests.post(f"{BASE_URL}/work-items/", json={"project_id": pid, "title": "B", "description": ""}).json()

    # approvals for both
    ar_a = requests.post(f"{BASE_URL}/work-items/{a['id']}/approvals").json()
    requests.post(f"{BASE_URL}/work-items/approvals/{ar_a['id']}/approve")
    ar_b = requests.post(f"{BASE_URL}/work-items/{b['id']}/approvals").json()
    requests.post(f"{BASE_URL}/work-items/approvals/{ar_b['id']}/approve")

    # enqueue B depends on A
    requests.post(f"{BASE_URL}/scheduler/enqueue", json={"work_item_id": a["id"]})
    requests.post(
        f"{BASE_URL}/scheduler/enqueue",
        json={"work_item_id": b["id"], "depends_on_work_item_id": a["id"]},
    )

    # first tick should start A only
    t1 = requests.post(f"{BASE_URL}/scheduler/tick").json()
    assert t1["processed"] == 1

    # find A's run and complete it
    runs_a = requests.get(f"{BASE_URL}/work-items/{a['id']}/runs").json()
    assert runs_a and runs_a[0]["status"] == "running"
    requests.post(f"{BASE_URL}/work-items/runs/{runs_a[0]['id']}/complete", params={"success": True})

    # second tick should start B
    t2 = requests.post(f"{BASE_URL}/scheduler/tick").json()
    assert t2["processed"] == 1

