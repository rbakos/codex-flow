#!/usr/bin/env python3
import os
import time
import shlex
import subprocess
from typing import List, Optional, Union

import requests
import yaml
import shutil
import json
import threading
import uuid


BASE_URL = os.getenv("ORCH_URL", "http://localhost:18080")
INTERVAL = float(os.getenv("AGENT_INTERVAL", "2.0"))
SHELL = os.getenv("AGENT_SHELL", "/bin/sh")
TICK_INTERVAL = float(os.getenv("AGENT_TICK_INTERVAL", "1.0"))
HEARTBEAT_INTERVAL = float(os.getenv("AGENT_HEARTBEAT_INTERVAL", "10.0"))
CLAIM_TTL = int(os.getenv("AGENT_CLAIM_TTL", "300"))
AGENT_ID = os.getenv("AGENT_ID", f"agent-{uuid.uuid4().hex[:8]}")


def tick() -> int:
    try:
        r = requests.post(f"{BASE_URL}/scheduler/tick")
        r.raise_for_status()
        return r.json().get("processed", 0)
    except Exception:
        return 0


def list_queue():
    return requests.get(f"{BASE_URL}/scheduler/queue").json()


def list_runs(wi_id: int):
    return requests.get(f"{BASE_URL}/work-items/{wi_id}/runs").json()


def get_tool_recipe_yaml(wi_id: int) -> Optional[str]:
    try:
        r = requests.get(f"{BASE_URL}/work-items/{wi_id}/tool-recipe")
        if r.status_code == 200:
            return r.json().get("yaml")
    except Exception:
        pass
    return None


def append_log(run_id: int, line: str):
    requests.post(
        f"{BASE_URL}/work-items/runs/{run_id}/logs",
        json={"line": line},
        headers={"content-type": "application/json"},
    )


def complete(run_id: int, success: bool = True):
    requests.post(f"{BASE_URL}/work-items/runs/{run_id}/complete", params={"success": success})


def load_steps_from_local_override() -> Optional[List[Union[str, dict]]]:
    """
    Development helper: allow defining steps via AGENT_STEPS env var (newline-separated),
    so we can demonstrate actual command execution without YAML exposure.
    """
    raw = os.getenv("AGENT_STEPS")
    if not raw:
        return None
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    return lines or None


def _post_step(run_id: int, name: str, status: str, duration: float | None = None, started_at: float | None = None, finished_at: float | None = None) -> Optional[int]:
    try:
        payload = {"name": name, "status": status, "duration_seconds": duration}
        import datetime as _dt
        if started_at is not None:
            payload["started_at"] = _dt.datetime.fromtimestamp(started_at).isoformat()
        if finished_at is not None:
            payload["finished_at"] = _dt.datetime.fromtimestamp(finished_at).isoformat()
        r = requests.post(
            f"{BASE_URL}/work-items/runs/{run_id}/steps",
            json=payload,
            headers={"content-type": "application/json"},
        )
        if r.ok:
            try:
                return r.json().get("id")
            except Exception:
                return None
    except Exception:
        return None
    return None


def run_steps(run_id: int, steps: List[Union[str, dict]]) -> bool:
    for step in steps:
        if isinstance(step, str):
            cmd = step
            env_over = None
            timeout = None
            cwd = None
        else:
            cmd = step.get("run", "").strip()
            env_over = step.get("env") if isinstance(step.get("env"), dict) else None
            timeout = step.get("timeout") if isinstance(step.get("timeout"), int) else None
            cwd = step.get("cwd") if isinstance(step.get("cwd"), str) else None
        if not cmd:
            append_log(run_id, "Agent: skipped empty step")
            continue
        append_log(run_id, f"Agent: exec -> {cmd}")
        try:
            # Emit start event
            t0 = time.time()
            step_id = _post_step(run_id, cmd, "running", None, started_at=t0, finished_at=None)
            proc = subprocess.Popen(
                cmd,
                shell=True,
                executable=SHELL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=cwd,
                env={**os.environ, **(env_over or {})},
            )
            assert proc.stdout is not None
            start = time.time()
            while True:
                line = proc.stdout.readline()
                if line:
                    append_log(run_id, line.rstrip())
                if proc.poll() is not None:
                    break
                if timeout and (time.time() - start) > timeout:
                    proc.kill()
                    append_log(run_id, "Agent: timeout exceeded; killed process")
                    return False
            rc = proc.returncode
            t1 = time.time()
            dt = t1 - t0
            append_log(run_id, f"Agent: exit code {rc}")
            append_log(run_id, f"Agent: step duration {dt:.3f}s")
            if step_id:
                try:
                    import datetime as _dt
                    requests.patch(
                        f"{BASE_URL}/work-items/runs/steps/{step_id}",
                        json={
                            "status": ("succeeded" if rc == 0 else "failed"),
                            "duration_seconds": dt,
                            "finished_at": _dt.datetime.fromtimestamp(t1).isoformat(),
                        },
                        headers={"content-type": "application/json"},
                    )
                except Exception:
                    pass
            else:
                _post_step(run_id, cmd, "succeeded" if rc == 0 else "failed", dt, started_at=t0, finished_at=t1)
            if rc != 0:
                return False
        except Exception as e:
            append_log(run_id, f"Agent: error: {e}")
            # Best-effort step event for error
            try:
                t1 = time.time()
                if step_id:
                    import datetime as _dt
                    requests.patch(
                        f"{BASE_URL}/work-items/runs/steps/{step_id}",
                        json={
                            "status": "error",
                            "duration_seconds": (t1 - t0),
                            "finished_at": _dt.datetime.fromtimestamp(t1).isoformat(),
                        },
                        headers={"content-type": "application/json"},
                    )
                else:
                    _post_step(run_id, cmd, "error", t1 - t0, started_at=t0, finished_at=t1)
            except Exception:
                pass
            return False
    return True


def get_work_item(wi_id: int) -> Optional[dict]:
    try:
        r = requests.get(f"{BASE_URL}/work-items/{wi_id}")
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def infer_steps_from_title(title: str) -> List[str]:
    t = title.lower()
    steps: List[str] = []
    if "build" in t:
        steps += [
            "echo '[build] resolve deps'",
            "echo '[build] compile/bundle'",
        ]
    if "test" in t or "unit" in t:
        steps += [
            "echo '[test] run unit tests'",
        ]
    if "integration" in t or "e2e" in t:
        steps += [
            "echo '[integration] run end-to-end tests'",
        ]
    if "plan" in t:
        steps += [
            "echo '[infra] plan changes'",
        ]
    if "apply" in t or "deploy" in t:
        steps += [
            "echo '[deploy] rollout changes'",
        ]
    if not steps:
        steps = [
            "echo 'start'",
            "uname -a || ver || systeminfo || true",
            "python --version || true",
            "echo 'done'",
        ]
    return steps


def main():
    print("Agent running against:", BASE_URL)
    print("Agent id:", AGENT_ID)
    processed_runs: set[int] = set()

    stop_evt = threading.Event()

    def _bg_ticker():
        while not stop_evt.is_set():
            try:
                tick()
            finally:
                stop_evt.wait(TICK_INTERVAL)

    t = threading.Thread(target=_bg_ticker, name="agent-bg-ticker", daemon=True)
    t.start()

    try:
        while True:
            # still call tick once at loop edge for responsiveness
            tick()
            try:
                queue = list_queue()
            except Exception:
                time.sleep(INTERVAL)
                continue

            for st in queue:
                if st.get("status") != "running":
                    continue
                wi_id = st["work_item_id"]
                runs = list_runs(wi_id)
                if not runs:
                    continue
                run = runs[-1]
                if run["status"] != "running" or run["id"] in processed_runs:
                    continue

                rid = run["id"]
                processed_runs.add(rid)

                # Claim run atomically and start heartbeat before doing any work
                try:
                    claimed = requests.post(
                        f"{BASE_URL}/work-items/runs/{rid}/claim",
                        json={"agent_id": AGENT_ID, "ttl_seconds": CLAIM_TTL},
                        headers={"content-type": "application/json"},
                    ).json()
                    if not claimed.get("success"):
                        append_log(rid, f"Agent: claim failed; held by {run.get('claimed_by')}")
                        continue
                except Exception as e:
                    append_log(rid, f"Agent: claim error: {e}")
                    continue

                # Heartbeat thread for the claimed run
                hb_stop = threading.Event()

                def _hb():
                    while not hb_stop.is_set():
                        try:
                            requests.post(
                                f"{BASE_URL}/work-items/runs/{rid}/heartbeat",
                                json={"agent_id": AGENT_ID},
                                headers={"content-type": "application/json"},
                            )
                        except Exception:
                            pass
                        hb_stop.wait(HEARTBEAT_INTERVAL)

                hb_t = threading.Thread(target=_hb, name=f"hb-{rid}", daemon=True)
                hb_t.start()

                # Steps source: prefer AGENT_STEPS env; else parse YAML 'steps'
                steps = load_steps_from_local_override()
                if not steps:
                    yaml_text = get_tool_recipe_yaml(wi_id)
                    if yaml_text:
                        try:
                            data = yaml.safe_load(yaml_text) or {}
                            steps = data.get("steps") or []
                            if not isinstance(steps, list):
                                steps = []
                        except Exception:
                            steps = []
                    if not steps:
                        wi = get_work_item(wi_id)
                        title = (wi or {}).get("title", "")
                        steps = infer_steps_from_title(title)

                # Plan capabilities and required inputs
                wi = get_work_item(wi_id) or {}
                title = (wi or {}).get("title", "")
                need_aws = "aws" in title.lower() or any("aws" in (s if isinstance(s, str) else s.get("run","")) for s in steps)
                need_gcp = any(x in title.lower() for x in ["gcp", "google", "gcloud"]) or any(
                    any(k in (s if isinstance(s, str) else s.get("run", "")) for k in ["gcloud", "gs://"]) for s in steps
                )
                need_az = any(x in title.lower() for x in ["azure", "az "]) or any(
                    " az " in (f" {s} " if isinstance(s, str) else f" {s.get('run','')} ") for s in steps
                )
                need_k8s = any(x in title.lower() for x in ["k8s", "kubernetes", "kubectl", "helm"]) or any(
                    any(k in (s if isinstance(s, str) else s.get("run", "")) for k in ["kubectl", "helm"]) for s in steps
                )
                required_env = {}
                if need_aws:
                    # Ensure CLI presence
                    if shutil.which("aws") is None:
                        append_log(rid, "Agent: AWS CLI not found; please install or use containerized agent.")
                    # Determine required inputs
                    for key in ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION"]:
                        if not os.getenv(key):
                            required_env[key] = ""
                    # Request if missing
                    if required_env:
                        prompt = "AWS credentials/region required to proceed. Provide values for the listed keys."
                        try:
                            req = requests.post(
                                f"{BASE_URL}/work-items/runs/{rid}/info-requests",
                                json={"prompt": prompt, "required_keys": list(required_env.keys())},
                                headers={"content-type": "application/json"},
                            ).json()
                            append_log(rid, "Agent: waiting for user-provided AWS configuration...")
                            # Poll for resolution
                            while True:
                                cur = requests.get(
                                    f"{BASE_URL}/work-items/runs/{rid}/info-requests",
                                    params={"plaintext": "1", "x_orch_secret": os.getenv("AGENT_SECRET_KEY", "")},
                                ).json()
                                found = next((x for x in cur if x["id"] == req["id"]), None)
                                if found and found.get("status") == "resolved":
                                    vals = found.get("responses") or {}
                                    for k, v in vals.items():
                                        if isinstance(k, str) and isinstance(v, str):
                                            os.environ[k] = v
                                    append_log(rid, "Agent: received AWS configuration; continuing.")
                                    break
                                time.sleep(1.0)
                        except Exception as e:
                            append_log(rid, f"Agent: failed to create info request: {e}")

                if need_gcp:
                    if shutil.which("gcloud") is None:
                        append_log(rid, "Agent: gcloud not found; please install or use containerized agent.")
                    required_env = {}
                    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON"):
                        required_env["GOOGLE_APPLICATION_CREDENTIALS_JSON"] = ""
                    if not os.getenv("GOOGLE_CLOUD_PROJECT") and not os.getenv("CLOUDSDK_CORE_PROJECT"):
                        required_env["GOOGLE_CLOUD_PROJECT"] = ""
                    if required_env:
                        prompt = "GCP credentials (service account JSON) and project ID required to proceed."
                        try:
                            req = requests.post(
                                f"{BASE_URL}/work-items/runs/{rid}/info-requests",
                                json={"prompt": prompt, "required_keys": list(required_env.keys())},
                                headers={"content-type": "application/json"},
                            ).json()
                            append_log(rid, "Agent: waiting for user-provided GCP configuration...")
                            while True:
                                cur = requests.get(
                                    f"{BASE_URL}/work-items/runs/{rid}/info-requests",
                                    params={"plaintext": "1", "x_orch_secret": os.getenv("AGENT_SECRET_KEY", "")},
                                ).json()
                                found = next((x for x in cur if x["id"] == req["id"]), None)
                                if found and found.get("status") == "resolved":
                                    vals = found.get("responses") or {}
                                    # If JSON provided, write to temp file
                                    creds_json = vals.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
                                    if isinstance(creds_json, str) and creds_json.strip():
                                        import tempfile, pathlib

                                        fd, path = tempfile.mkstemp(prefix="gcp-creds-", suffix=".json")
                                        with os.fdopen(fd, "w") as f:
                                            f.write(creds_json)
                                        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
                                    for k, v in vals.items():
                                        if isinstance(k, str) and isinstance(v, str):
                                            if k != "GOOGLE_APPLICATION_CREDENTIALS_JSON":
                                                os.environ[k] = v
                                    append_log(rid, "Agent: received GCP configuration; continuing.")
                                    break
                                time.sleep(1.0)
                        except Exception as e:
                            append_log(rid, f"Agent: failed to create info request: {e}")

                if need_az:
                    if shutil.which("az") is None:
                        append_log(rid, "Agent: Azure CLI not found; please install or use containerized agent.")
                    required_env = {}
                    for key in ["AZURE_CLIENT_ID", "AZURE_TENANT_ID", "AZURE_CLIENT_SECRET", "AZURE_SUBSCRIPTION_ID"]:
                        if not os.getenv(key):
                            required_env[key] = ""
                    if required_env:
                        prompt = "Azure service principal credentials required to proceed."
                        try:
                            req = requests.post(
                                f"{BASE_URL}/work-items/runs/{rid}/info-requests",
                                json={"prompt": prompt, "required_keys": list(required_env.keys())},
                                headers={"content-type": "application/json"},
                            ).json()
                            append_log(rid, "Agent: waiting for user-provided Azure configuration...")
                            while True:
                                cur = requests.get(
                                    f"{BASE_URL}/work-items/runs/{rid}/info-requests",
                                    params={"plaintext": "1", "x_orch_secret": os.getenv("AGENT_SECRET_KEY", "")},
                                ).json()
                                found = next((x for x in cur if x["id"] == req["id"]), None)
                                if found and found.get("status") == "resolved":
                                    vals = found.get("responses") or {}
                                    for k, v in vals.items():
                                        if isinstance(k, str) and isinstance(v, str):
                                            os.environ[k] = v
                                    append_log(rid, "Agent: received Azure configuration; continuing.")
                                    break
                                time.sleep(1.0)
                        except Exception as e:
                            append_log(rid, f"Agent: failed to create info request: {e}")

                if need_k8s:
                    # Prefer kubeconfig content provided directly
                    required_env = {}
                    if not os.getenv("KUBECONFIG") and not os.getenv("KUBECONFIG_CONTENT"):
                        required_env["KUBECONFIG_CONTENT"] = ""
                    if required_env:
                        prompt = "Kubernetes access required. Provide KUBECONFIG content (base64 or raw)."
                        try:
                            req = requests.post(
                                f"{BASE_URL}/work-items/runs/{rid}/info-requests",
                                json={"prompt": prompt, "required_keys": list(required_env.keys())},
                                headers={"content-type": "application/json"},
                            ).json()
                            append_log(rid, "Agent: waiting for user-provided K8s configuration...")
                            while True:
                                cur = requests.get(
                                    f"{BASE_URL}/work-items/runs/{rid}/info-requests",
                                    params={"plaintext": "1", "x_orch_secret": os.getenv("AGENT_SECRET_KEY", "")},
                                ).json()
                                found = next((x for x in cur if x["id"] == req["id"]), None)
                                if found and found.get("status") == "resolved":
                                    vals = found.get("responses") or {}
                                    content = vals.get("KUBECONFIG_CONTENT")
                                    if isinstance(content, str) and content.strip():
                                        import tempfile, base64

                                        data = content
                                        try:
                                            data = base64.b64decode(content).decode("utf-8")
                                        except Exception:
                                            pass
                                        fd, path = tempfile.mkstemp(prefix="kubeconfig-", suffix=".yaml")
                                        with os.fdopen(fd, "w") as f:
                                            f.write(data)
                                        os.environ["KUBECONFIG"] = path
                                    append_log(rid, "Agent: received K8s configuration; continuing.")
                                    break
                                time.sleep(1.0)
                        except Exception as e:
                            append_log(rid, f"Agent: failed to create info request: {e}")

                append_log(rid, "Agent: starting execution")
                try:
                    ok = run_steps(rid, steps)
                    append_log(rid, "Agent: finishing")
                    complete(rid, success=ok)
                finally:
                    hb_stop.set()
                    hb_t.join(timeout=2.0)

            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        stop_evt.set()
        t.join(timeout=2.0)


if __name__ == "__main__":
    main()
