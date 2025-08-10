(function () {
  const $ = (id) => document.getElementById(id);
  const status = $("status");
  const lsKey = "orch.baseUrl";
  const defaultBase = window.location.origin;
  const baseInput = $("baseUrl");
  baseInput.value = localStorage.getItem(lsKey) || defaultBase;
  function base() {
    return baseInput.value || defaultBase;
  }
  $("saveBase").onclick = () => {
    localStorage.setItem(lsKey, base());
    status.textContent = `Saved ${base()}`;
    setTimeout(() => (status.textContent = ""), 1500);
  };

  async function jget(path) {
    const r = await fetch(`${base()}${path}`);
    if (!r.ok) throw new Error(`GET ${path} -> ${r.status}`);
    return r.json();
  }
  async function jpost(path, body) {
    const r = await fetch(`${base()}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!r.ok) throw new Error(`POST ${path} -> ${r.status}`);
    return r.json();
  }

  // Projects
  async function refreshProjects() {
    // no list projects endpoint; show a hint
    $("projects").innerHTML = `<li>Use create + copy the returned project_id from responses below.</li>`;
  }
  $("refreshProjects").onclick = refreshProjects;
  $("createProject").onclick = async () => {
    const name = $("projName").value;
    const description = $("projDesc").value;
    const p = await jpost("/projects/", { name, description });
    $("projects").innerHTML = `<li>Created: ${p.id} ${p.name}</li>`;
  };

  // Work Items
  $("createWI").onclick = async () => {
    const project_id = parseInt($("wiProjectId").value, 10);
    const title = $("wiTitle").value;
    const description = $("wiDesc").value;
    const wi = await jpost("/work-items/", { project_id, title, description });
    alert(`Created WI ${wi.id}`);
  };
  $("requestApproval").onclick = async () => {
    const wiId = parseInt($("wiId").value, 10);
    const r = await jpost(`/work-items/${wiId}/approvals`, {});
    $("runs").textContent = JSON.stringify(r, null, 2);
  };
  $("approve").onclick = async () => {
    const approvalId = parseInt($("approvalId").value, 10);
    const r = await jpost(`/work-items/approvals/${approvalId}/approve`);
    $("runs").textContent = JSON.stringify(r, null, 2);
  };
  $("startRun").onclick = async () => {
    const wiId = parseInt($("wiId").value, 10);
    const r = await jpost(`/work-items/${wiId}/start`);
    $("runId").value = r.id;
    $("runs").textContent = JSON.stringify(r, null, 2);
  };
  $("completeRun").onclick = async () => {
    const runId = parseInt($("runId").value, 10);
    const r = await jpost(`/work-items/runs/${runId}/complete?success=true`);
    $("runs").textContent = JSON.stringify(r, null, 2);
  };
  $("listRuns").onclick = async () => {
    const wiId = parseInt($("wiId").value, 10);
    const r = await jget(`/work-items/${wiId}/runs`);
    $("runs").textContent = JSON.stringify(r, null, 2);
    if (r && r.length) $("runId").value = r[r.length - 1].id;
  };
  $("getLogs").onclick = async () => {
    const runId = parseInt($("runId").value, 10);
    const r = await fetch(`${base()}/work-items/runs/${runId}/logs`);
    $("logs").textContent = await r.text();
  };
  $("streamLogs").onclick = async () => {
    const runId = parseInt($("runId").value, 10);
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${new URL(base()).host}/work-items/runs/${runId}/logs/ws`);
    $("logs").textContent = "";
    ws.onmessage = (ev) => {
      $("logs").textContent += ev.data + "\n";
    };
    ws.onerror = () => alert("WebSocket error");
  };

  // Scheduler
  $("enqueue").onclick = async () => {
    const work_item_id = parseInt($("enqId").value, 10);
    const depends_on_work_item_id = $("depId").value ? parseInt($("depId").value, 10) : undefined;
    const priority = $("prio").value ? parseInt($("prio").value, 10) : 0;
    const delay_seconds = $("delay").value ? parseInt($("delay").value, 10) : 0;
    const r = await jpost(`/scheduler/enqueue`, { work_item_id, depends_on_work_item_id, priority, delay_seconds });
    $("queueView").textContent = JSON.stringify(r, null, 2);
  };
  $("tick").onclick = async () => {
    const r = await jpost(`/scheduler/tick`);
    $("queueView").textContent = JSON.stringify(r, null, 2);
  };
  $("queue").onclick = async () => {
    const r = await jget(`/scheduler/queue`);
    $("queueView").textContent = JSON.stringify(r, null, 2);
  };

  // Requeue
  $("requeueWI").onclick = async () => {
    const work_item_id = parseInt($("rqWiId").value, 10);
    const priority = $("rqPrio").value ? parseInt($("rqPrio").value, 10) : 0;
    const delay_seconds = $("rqDelay").value ? parseInt($("rqDelay").value, 10) : 0;
    const r = await jpost(`/scheduler/requeue/work-item`, { work_item_id, priority, delay_seconds });
    $("queueView").textContent = JSON.stringify(r, null, 2);
  };
  $("requeueRun").onclick = async () => {
    const run_id = parseInt($("rqRunId").value, 10);
    const priority = $("rqRunPrio").value ? parseInt($("rqRunPrio").value, 10) : 0;
    const backoff = $("rqBackoff").checked;
    const delay_seconds = $("rqRunDelay").value ? parseInt($("rqRunDelay").value, 10) : undefined;
    const r = await jpost(`/scheduler/requeue/run/${run_id}`, { priority, backoff, delay_seconds });
    $("queueView").textContent = JSON.stringify(r, null, 2);
  };

  // Info Requests
  $("listIR").onclick = async () => {
    const runId = parseInt($("irRunId").value, 10);
    const r = await jget(`/work-items/runs/${runId}/info-requests`);
    $("irView").textContent = JSON.stringify(r, null, 2);
  };
  $("respondIR").onclick = async () => {
    const reqId = parseInt($("irReqId").value, 10);
    const values = JSON.parse($("irValues").value || "{}");
    const r = await jpost(`/work-items/runs/info-requests/${reqId}/respond`, { values });
    $("irView").textContent = JSON.stringify(r, null, 2);
  };

  refreshProjects();
})();
