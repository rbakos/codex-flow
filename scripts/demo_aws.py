#!/usr/bin/env python3
import os
import time
import sys
import json
import requests


BASE_URL = os.getenv("ORCH_URL", "http://localhost:18080")


def post(path: str, **kwargs):
    r = requests.post(f"{BASE_URL}{path}", **kwargs)
    if not r.ok:
        raise RuntimeError(f"POST {path} failed: {r.status_code} {r.text}")
    return r


def get(path: str, **kwargs):
    r = requests.get(f"{BASE_URL}{path}", **kwargs)
    if not r.ok:
        raise RuntimeError(f"GET {path} failed: {r.status_code} {r.text}")
    return r


def main():
    print(f"Using orchestrator: {BASE_URL}")
    # 1) Project
    proj = post(
        "/projects/",
        json={"name": f"demo-aws-{int(time.time())}", "description": "demo deploy to aws"},
        headers={"content-type": "application/json"},
    ).json()
    pid = proj["id"]
    print("Created project", pid)

    # 2) Work item (title includes 'aws' to trigger planner)
    wi = post(
        "/work-items/",
        json={"project_id": pid, "title": "deploy:prod to aws", "description": "demo"},
        headers={"content-type": "application/json"},
    ).json()
    wi_id = wi["id"]
    print("Created work item", wi_id)

    # 3) Approval and approve (required by policy)
    ar = post(f"/work-items/{wi_id}/approvals").json()
    post(f"/work-items/approvals/{ar['id']}/approve")
    print("Approved work item")

    # 4) Enqueue and tick
    post("/scheduler/enqueue", json={"work_item_id": wi_id}, headers={"content-type": "application/json"})
    post("/scheduler/tick")

    # 5) Find run
    run_id = None
    for _ in range(20):
        runs = get(f"/work-items/{wi_id}/runs").json()
        if runs:
            run_id = runs[-1]["id"]
            break
        time.sleep(1)
    if not run_id:
        print("No run found yet. Ensure agent is running (make agent or make up-agent).", file=sys.stderr)
        sys.exit(2)
    print("Run id:", run_id)

    # 6) Wait for info request from agent (if agent detects missing AWS inputs)
    print("Waiting for info request from agent (if credentials missing)...")
    req = None
    for _ in range(60):
        items = get(f"/work-items/runs/{run_id}/info-requests").json()
        if items:
            req = items[-1]
            break
        time.sleep(1)

    if not req:
        print("No info request yet. Agent may have enough env to proceed or is not running.")
        print(json.dumps({"run_id": run_id, "info_request": None}, indent=2))
        return

    print("Info request created:")
    print(json.dumps(req, indent=2))
    print()
    print("To respond, run:")
    print(
        f"curl -sX POST {BASE_URL}/work-items/runs/info-requests/{req['id']}/respond "
        "-H 'content-type: application/json' "
        "-d '{\"values\":{\"AWS_ACCESS_KEY_ID\":\"...\",\"AWS_SECRET_ACCESS_KEY\":\"...\",\"AWS_DEFAULT_REGION\":\"us-east-1\"}}'"
    )
    print()
    print("Then tail logs:")
    print(f"curl -s {BASE_URL}/work-items/runs/{run_id}/logs")


if __name__ == "__main__":
    main()

