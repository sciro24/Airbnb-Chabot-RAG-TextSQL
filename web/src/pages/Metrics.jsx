import { useEffect, useState } from "react";
import { getMetrics, getHealth, resetMetrics } from "../api.js";

export default function Metrics() {
  const [metrics, setMetrics] = useState(null);
  const [health, setHealth] = useState(null);
  const [probing, setProbing] = useState(false);

  async function refresh() {
    setMetrics(await getMetrics());
    setHealth(await getHealth(false));
  }
  useEffect(() => {
    refresh();
  }, []);

  async function probe() {
    setProbing(true);
    setHealth(await getHealth(true));
    setProbing(false);
  }

  if (!metrics || !health) return <div className="page">Carico…</div>;

  const st = (v) => (v === "ok" ? "🟢 ok" : v ? "🔴 " + v : "—");

  return (
    <div className="page metrics">
      <h1>📊 Osservabilità &amp; Metriche</h1>

      <h2>Collegamento endpoint</h2>
      <table>
        <tbody>
          <tr><td>Host Databricks</td><td>{health.host || "—"}</td></tr>
          <tr><td>Endpoint LLM</td><td>{health.llm_endpoint} {health.llm && st(health.llm)}</td></tr>
          <tr><td>Endpoint embedding</td><td>{health.embedding_endpoint} {health.embedding && st(health.embedding)}</td></tr>
          <tr><td>SQL Warehouse</td><td>{health.sql_warehouse ? "🟢 configurato" : "🔴"} {health.sql && st(health.sql)}</td></tr>
          <tr><td>Vector Search index</td><td>{health.vs_index}</td></tr>
          <tr><td>Reranker</td><td>{health.reranker_model}</td></tr>
        </tbody>
      </table>
      <button onClick={probe} disabled={probing}>
        {probing ? "Test in corso…" : "Testa endpoint (live)"}
      </button>

      <h2>Richieste</h2>
      <div className="cards">
        <div className="card"><span>{sum(metrics.intent_counts)}</span>intent totali</div>
        <div className="card"><span>{metrics.cache_hits}</span>cache hit</div>
        <div className="card"><span>{metrics.cache_misses}</span>cache miss</div>
        <div className="card"><span>{(metrics.cache_hit_ratio * 100).toFixed(0)}%</span>hit ratio</div>
      </div>
      {Object.keys(metrics.intent_counts).length > 0 && (
        <p>Per intent: {JSON.stringify(metrics.intent_counts)}</p>
      )}

      <h2>Latenza per fase (ms)</h2>
      {Object.keys(metrics.phases).length === 0 ? (
        <p>Nessuna richiesta registrata.</p>
      ) : (
        <table>
          <thead><tr><th>fase</th><th>count</th><th>avg</th><th>ultima</th></tr></thead>
          <tbody>
            {Object.entries(metrics.phases).map(([p, v]) => (
              <tr key={p}><td>{p}</td><td>{v.count}</td><td>{v.avg_ms}</td><td>{v.last_ms}</td></tr>
            ))}
          </tbody>
        </table>
      )}

      {Object.keys(metrics.errors).length > 0 && (
        <p className="err">Errori: {JSON.stringify(metrics.errors)}</p>
      )}

      <div className="row">
        <button onClick={refresh}>Aggiorna</button>
        <button onClick={() => resetMetrics().then(refresh)}>Reset metriche</button>
      </div>
    </div>
  );
}

function sum(obj) {
  return Object.values(obj || {}).reduce((a, b) => a + b, 0);
}
