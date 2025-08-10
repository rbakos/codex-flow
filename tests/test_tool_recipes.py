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


def test_tool_recipe_validation():
    # Create project + work item
    pr = requests.post(f"{BASE_URL}/projects/", json={"name": "tools-demo", "description": ""}).json()
    wi = requests.post(
        f"{BASE_URL}/work-items/",
        json={"project_id": pr["id"], "title": "Tooling", "description": ""},
    ).json()

    valid_yaml = """
tools:
  - name: awscli
    version: 2.15.0
    checksum: sha256:deadbeef
    env: { AWS_DEFAULT_REGION: us-east-1 }
    network: true
  - name: opentofu
    version: 1.7.0
    network: false
"""
    r1 = requests.post(f"{BASE_URL}/work-items/{wi['id']}/tool-recipe", json={"yaml": valid_yaml})
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "valid"

    invalid_yaml = """
tools:
  - name: kubectl
    # version is missing
"""
    r2 = requests.post(f"{BASE_URL}/work-items/{wi['id']}/tool-recipe", json={"yaml": invalid_yaml})
    assert r2.status_code == 200
    body = r2.json()
    assert body["status"] == "invalid"
    assert "version" in body["error"]

