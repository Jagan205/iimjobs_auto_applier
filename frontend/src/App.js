import React, { useEffect, useState } from "react";

const API_BASE = "http://127.0.0.1:7001";

function PillList({ title, items, value, setValue, onAdd, onRemove, placeholder }) {
  return (
    <div className="card">
      <h3>{title}</h3>
      <div className="row">
        <input
          className="input"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onAdd()}
          placeholder={placeholder}
        />
        <button className="btn" onClick={onAdd}>Add</button>
      </div>

      <div style={{ marginTop: 12 }}>
        {items.map((k) => (
          <span key={k} className="keyword">
            {k}
            <button
              onClick={() => onRemove(k)}
              style={{
                border: "none",
                background: "transparent",
                color: "#fca5a5",
                cursor: "pointer",
                fontWeight: 800
              }}
            >
              x
            </button>
          </span>
        ))}
      </div>
    </div>
  );
}

export default function App() {
  const [status, setStatus] = useState(null);
  const [roles, setRoles] = useState([]);
  const [jdKeywords, setJdKeywords] = useState([]);
  const [locations, setLocations] = useState([]);
  const [newRole, setNewRole] = useState("");
  const [newKeyword, setNewKeyword] = useState("");
  const [newLocation, setNewLocation] = useState("");
  const [applied, setApplied] = useState([]);

  async function loadStatus() {
    try {
      const res = await fetch(`${API_BASE}/api/status`);
      const data = await res.json();
      setStatus(data);

      const cfg = data.config || {};
      setRoles(cfg.roles || data.keywords || []);
      setJdKeywords(cfg.jd_keywords || []);
      setLocations(cfg.locations || []);
    } catch {
      setStatus({ ok: false });
    }
  }

  async function loadApplied() {
    try {
      const res = await fetch(`${API_BASE}/api/applied`);
      const data = await res.json();
      setApplied(data || []);
    } catch {
      setApplied([]);
    }
  }

  async function saveConfig(nextRoles = roles, nextKeywords = jdKeywords, nextLocations = locations) {
    setRoles(nextRoles);
    setJdKeywords(nextKeywords);
    setLocations(nextLocations);

    await fetch(`${API_BASE}/api/config`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        roles: nextRoles,
        jd_keywords: nextKeywords,
        locations: nextLocations
      }),
    });

    loadStatus();
  }

  useEffect(() => {
    loadStatus();
    loadApplied();
    const iv = setInterval(() => {
      loadStatus();
      loadApplied();
    }, 2000);
    return () => clearInterval(iv);
  }, []);

  function addRole() {
    const k = newRole.trim();
    if (!k || roles.includes(k)) return;
    saveConfig([...roles, k], jdKeywords, locations);
    setNewRole("");
  }

  function addKeyword() {
    const k = newKeyword.trim();
    if (!k || jdKeywords.includes(k)) return;
    saveConfig(roles, [...jdKeywords, k], locations);
    setNewKeyword("");
  }

  function addLocation() {
    const k = newLocation.trim();
    if (!k || locations.includes(k)) return;
    saveConfig(roles, jdKeywords, [...locations, k]);
    setNewLocation("");
  }

  function removeRole(k) {
    saveConfig(roles.filter((x) => x !== k), jdKeywords, locations);
  }

  function removeKeyword(k) {
    saveConfig(roles, jdKeywords.filter((x) => x !== k), locations);
  }

  function removeLocation(k) {
    saveConfig(roles, jdKeywords, locations.filter((x) => x !== k));
  }

  async function startBot() {
    await fetch(`${API_BASE}/api/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ roles, jd_keywords: jdKeywords, locations }),
    });
    loadStatus();
  }

  async function stopBot() {
    await fetch(`${API_BASE}/api/stop`, { method: "POST" });
    loadStatus();
  }

  const state = status?.state || {};
  const logs = state.logs || [];

  return (
    <div className="container">
      <div className="header">
        <div style={{ fontSize: 12, color: "#a5b4fc", letterSpacing: 1 }}>
          IIMJOBS AUTOMATION
        </div>
        <h1 style={{ margin: "8px 0 4px" }}>Auto Apply Jobs</h1>
        <div style={{ color: "#9ca3af" }}>
          Apply only when Job Role AND JD Keyword AND Location match.
        </div>
      </div>

      <div className="card">
        <h3>Backend Status</h3>
        {status?.ok ? (
          <span className="badge green">Backend online</span>
        ) : (
          <span className="badge red">Backend offline</span>
        )}
        {state.running ? (
          <span className="badge green">Bot running</span>
        ) : (
          <span className="badge">Bot idle</span>
        )}
        <span className="badge">Applied: {state.applied || 0}</span>
        <span className="badge">Skipped: {state.skipped || 0}</span>
        <span className="badge">Failed: {state.failed || 0}</span>
      </div>

      <PillList
        title="1. Job Roles - required"
        items={roles}
        value={newRole}
        setValue={setNewRole}
        onAdd={addRole}
        onRemove={removeRole}
        placeholder="Example: Chief of Staff, Product Manager, Data Engineer"
      />

      <PillList
        title="2. JD Keywords - required"
        items={jdKeywords}
        value={newKeyword}
        setValue={setNewKeyword}
        onAdd={addKeyword}
        onRemove={removeKeyword}
        placeholder="Example: Pharmaceutical, Life Science, Strategy, M&A"
      />

      <PillList
        title="3. Locations - optional"
        items={locations}
        value={newLocation}
        setValue={setNewLocation}
        onAdd={addLocation}
        onRemove={removeLocation}
        placeholder="Example: Mumbai, Bengaluru, Remote"
      />

      <div className="card">
        <h3>Matching Rule</h3>
        <div style={{ color: "#cbd5e1", lineHeight: 1.8 }}>
          Bot applies only if:
          <br />
          <b>Job Role match</b> AND <b>JD Keyword match</b> AND <b>Location match</b>
          <br />
          If Locations are empty, all locations are allowed.
        </div>
      </div>

      <div className="card">
        <h3>Controls</h3>
        <div className="row">
          <button
            className="btn"
            onClick={startBot}
            disabled={state.running || roles.length === 0 || jdKeywords.length === 0}
          >
            Start Apply
          </button>
          <button className="btn danger" onClick={stopBot}>Stop</button>
          <button className="btn secondary" onClick={() => { loadStatus(); loadApplied(); }}>
            Refresh
          </button>
        </div>
        <p style={{ color: "#9ca3af", fontSize: 13 }}>
          First run lo browser visible ga open avuthundi. Captcha/OTP unte manually complete cheyyali.
        </p>
      </div>

      <div className="card">
        <h3>Current Activity</h3>
        <div>Role: <b>{state.current_keyword || "-"}</b></div>
        <div>Job: <b>{state.current_job || "-"}</b></div>
      </div>

      <div className="card">
        <h3>Logs</h3>
        <div className="logbox">
          {logs.length ? logs.join("\n") : "No logs yet."}
        </div>
      </div>

      <div className="card">
        <h3>Applied / Skipped History</h3>
        {applied.length === 0 ? (
          <div style={{ color: "#9ca3af" }}>No tracked jobs yet.</div>
        ) : (
          applied.slice().reverse().map((j, idx) => (
            <div key={idx} style={{ borderBottom: "1px solid #374151", padding: "10px 0" }}>
              <div><b>{j.title}</b></div>
              <div style={{ color: "#9ca3af", fontSize: 13 }}>
                {j.role || j.keyword} · {j.status} · {j.applied_at}
              </div>
              <div style={{ color: "#94a3b8", fontSize: 12 }}>{j.reason}</div>
              <a href={j.url} target="_blank" rel="noreferrer" style={{ color: "#a5b4fc" }}>
                Open Job
              </a>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
