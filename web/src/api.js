// Helper fetch verso il backend FastAPI.

export async function getListings() {
  const r = await fetch("/api/listings");
  return r.json();
}

export async function getGeojson() {
  const r = await fetch("/api/neighbourhoods.geojson");
  return r.json();
}

export async function getNeighbourhoods() {
  const r = await fetch("/api/neighbourhoods");
  return r.json();
}

export async function getMetrics() {
  const r = await fetch("/api/metrics");
  return r.json();
}

export async function getHealth(probe = false) {
  const r = await fetch(`/api/health?probe=${probe}`);
  return r.json();
}

export async function resetMetrics() {
  await fetch("/api/metrics/reset", { method: "POST" });
}

// Chat in streaming: POST + parsing SSE dal ReadableStream.
// onMeta(meta), onToken(text), onDone() sono callback.
export async function streamChat(query, scope, { onMeta, onToken, onDone }) {
  const resp = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, scope }),
  });
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop(); // ultimo pezzo incompleto resta nel buffer
    for (const part of parts) {
      let event = "message";
      let data = "";
      for (const line of part.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7).trim();
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (!data) continue;
      const payload = JSON.parse(data);
      if (event === "meta") onMeta && onMeta(payload);
      else if (event === "token") onToken && onToken(payload.text);
      else if (event === "done") onDone && onDone();
    }
  }
}
