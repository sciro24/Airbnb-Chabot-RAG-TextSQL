import { useEffect, useState } from "react";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid,
  PieChart, Pie, Cell, Legend,
} from "recharts";
import { getMetrics, getHealth, resetMetrics } from "../api.js";

const COLORS = ["#6366f1", "#06d6a0", "#ffd166", "#ef476f", "#3a86ff", "#8338ec"];

export default function Metrics() {
  const [metrics, setMetrics] = useState(null);
  const [health, setHealth] = useState(null);
  const [probing, setProbing] = useState(false);

  async function refresh() {
    setMetrics(await getMetrics());
    setHealth(await getHealth(false));
  }
  useEffect(() => { refresh(); }, []);

  async function probe() {
    setProbing(true);
    setHealth(await getHealth(true));
    setProbing(false);
  }

  if (!metrics || !health) return <div className="page">Carico…</div>;

  const st = (v) => (v === "ok" ? "🟢" : v ? "🔴" : "—");
  const phaseData = Object.entries(metrics.phases).map(([fase, v]) => ({
    fase, avg: v.avg_ms, count: v.count,
  }));
  const intentData = Object.entries(metrics.intent_counts).map(([name, value]) => ({ name, value }));
  const cacheData = [
    { name: "hit", value: metrics.cache_hits },
    { name: "miss", value: metrics.cache_misses },
  ];
  const totalReq = Object.values(metrics.intent_counts).reduce((a, b) => a + b, 0);
  const genAvg = metrics.phases.generate?.avg_ms ?? 0;

  return (
    <div className="page metrics">
      <div className="metrics-head">
        <h1>📊 Osservabilità &amp; Metriche</h1>
        <div className="row">
          <button onClick={refresh}>Aggiorna</button>
          <button onClick={() => resetMetrics().then(refresh)}>Reset</button>
        </div>
      </div>

      {/* KPI */}
      <div className="cards">
        <div className="card"><span>{totalReq}</span>richieste</div>
        <div className="card"><span>{(metrics.cache_hit_ratio * 100).toFixed(0)}%</span>cache hit ratio</div>
        <div className="card"><span>{genAvg}</span>ms media generazione</div>
        <div className="card"><span>{Object.values(metrics.errors).reduce((a, b) => a + b, 0)}</span>errori</div>
      </div>

      {/* Griglia grafici + info */}
      <div className="grid2">
        <div className="panel">
          <h3>Efficienza — latenza media per fase (ms)</h3>
          {phaseData.length ? (
            <ResponsiveContainer width="100%" height={230}>
              <BarChart data={phaseData} margin={{ left: -10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="fase" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="avg" fill="#6366f1" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : <p className="muted">Nessun dato.</p>}
        </div>

        <div className="panel">
          <h3>Efficacia — distribuzione richieste per intent</h3>
          {intentData.length ? (
            <ResponsiveContainer width="100%" height={230}>
              <PieChart>
                <Pie data={intentData} dataKey="value" nameKey="name" outerRadius={80} label>
                  {intentData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                </Pie>
                <Legend />
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          ) : <p className="muted">Nessun dato.</p>}
        </div>

        <div className="panel">
          <h3>Cache — hit vs miss</h3>
          {metrics.cache_hits + metrics.cache_misses > 0 ? (
            <ResponsiveContainer width="100%" height={230}>
              <PieChart>
                <Pie data={cacheData} dataKey="value" nameKey="name" innerRadius={45} outerRadius={80} label>
                  <Cell fill="#06d6a0" /><Cell fill="#ef476f" />
                </Pie>
                <Legend />
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          ) : <p className="muted">Nessuna richiesta con cache.</p>}
        </div>

        <div className="panel">
          <h3>Throughput — chiamate per fase</h3>
          {phaseData.length ? (
            <ResponsiveContainer width="100%" height={230}>
              <BarChart data={phaseData} margin={{ left: -10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="fase" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="count" fill="#06d6a0" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : <p className="muted">Nessun dato.</p>}
        </div>
      </div>

      {/* Collegamento endpoint + info tecniche */}
      <div className="grid2">
        <div className="panel">
          <h3>Collegamento endpoint</h3>
          <table>
            <tbody>
              <tr><td>Host</td><td className="mono">{health.host || "—"}</td></tr>
              <tr><td>LLM</td><td>{health.llm_endpoint} {health.llm && st(health.llm)}</td></tr>
              <tr><td>Embedding</td><td>{health.embedding_endpoint} {health.embedding && st(health.embedding)}</td></tr>
              <tr><td>SQL Warehouse</td><td>{health.sql_warehouse ? "🟢 configurato" : "🔴"} {health.sql && st(health.sql)}</td></tr>
            </tbody>
          </table>
          <button onClick={probe} disabled={probing}>{probing ? "Test…" : "Testa endpoint (live)"}</button>
        </div>
        <div className="panel">
          <h3>Info tecniche</h3>
          <table>
            <tbody>
              <tr><td>Vector Search index</td><td className="mono">{health.vs_index}</td></tr>
              <tr><td>Reranker</td><td className="mono">{health.reranker_model}</td></tr>
              <tr><td>Intent per tipo</td><td className="mono">{JSON.stringify(metrics.intent_counts)}</td></tr>
              {Object.keys(metrics.errors).length > 0 && (
                <tr><td>Errori</td><td className="err mono">{JSON.stringify(metrics.errors)}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
