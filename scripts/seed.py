#!/usr/bin/env python3
import os
import requests


BASE_URL = os.getenv("ORCH_URL", "http://localhost:18080")


def main():
    p = requests.post(f"{BASE_URL}/projects/", json={"name": "sample", "description": "seeded"}).json()
    pid = p["id"]
    requests.post(f"{BASE_URL}/projects/{pid}/vision", json={"content": "Build orchestrator sample"})
    requests.post(f"{BASE_URL}/projects/{pid}/requirements/propose")

    wi1 = requests.post(
        f"{BASE_URL}/work-items/", json={"project_id": pid, "title": "Scaffold app", "description": ""}
    ).json()
    wi2 = requests.post(
        f"{BASE_URL}/work-items/", json={"project_id": pid, "title": "Set up CI", "description": ""}
    ).json()

    # approvals
    a1 = requests.post(f"{BASE_URL}/work-items/{wi1['id']}/approvals").json()
    requests.post(f"{BASE_URL}/work-items/approvals/{a1['id']}/approve")
    a2 = requests.post(f"{BASE_URL}/work-items/{wi2['id']}/approvals").json()
    requests.post(f"{BASE_URL}/work-items/approvals/{a2['id']}/approve")

    # enqueue with dependency
    requests.post(f"{BASE_URL}/scheduler/enqueue", json={"work_item_id": wi1["id"]})
    requests.post(
        f"{BASE_URL}/scheduler/enqueue",
        json={"work_item_id": wi2["id"], "depends_on_work_item_id": wi1["id"]},
    )
    print("Seed complete. Visit:", BASE_URL)


if __name__ == "__main__":
    main()

