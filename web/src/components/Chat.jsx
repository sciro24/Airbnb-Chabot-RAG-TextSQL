import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { streamChat } from "../api.js";

function ScopeBanner({ scope, onClear }) {
  let label = "tutta Roma";
  if (scope?.kind === "listing") label = `annuncio «${scope.label}»`;
  else if (scope?.kind === "neighbourhood") label = `quartiere «${scope.neighbourhood}»`;
  return (
    <div className="scope">
      Ambito: <b>{label}</b>
      {scope && (
        <button className="link" onClick={onClear}>✖ rimuovi</button>
      )}
    </div>
  );
}

function Details({ meta }) {
  if (!meta) return null;
  if (meta.sql) {
    return (
      <details className="details">
        <summary>SQL eseguita · {meta.row_count} righe</summary>
        <pre>{meta.sql}</pre>
      </details>
    );
  }
  if (meta.contexts?.length) {
    return (
      <details className="details">
        <summary>Recensioni usate ({meta.contexts.length})</summary>
        {meta.contexts.map((c, i) => (
          <blockquote key={i}>
            <b>{c.neighbourhood}</b> (score {c.score}) — {c.text}
          </blockquote>
        ))}
      </details>
    );
  }
  return null;
}

export default function Chat({ scope, setScope, neighbourhoods, seed, onSeedConsumed }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send(text) {
    if (!text.trim() || busy) return;
    setBusy(true);
    setMessages((m) => [...m, { role: "user", text }]);
    const idx = messages.length + 1;
    setMessages((m) => [...m, { role: "assistant", answer: "", meta: null }]);
    try {
      await streamChat(text, scope, {
        onMeta: (meta) =>
          setMessages((m) => {
            const c = [...m];
            c[idx] = { ...c[idx], intent: meta.intent, meta };
            return c;
          }),
        onToken: (t) =>
          setMessages((m) => {
            const c = [...m];
            c[idx] = { ...c[idx], answer: (c[idx].answer || "") + t };
            return c;
          }),
      });
    } catch (e) {
      setMessages((m) => {
        const c = [...m];
        c[idx] = { ...c[idx], answer: "Errore: " + e.message };
        return c;
      });
    } finally {
      setBusy(false);
    }
  }

  // Domanda "seed" arrivata dalla mappa (annuncio selezionato).
  useEffect(() => {
    if (seed) {
      send(seed);
      onSeedConsumed();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed]);

  const last = messages[messages.length - 1];
  const showClarify = last?.role === "assistant" && last.meta?.clarify;

  function pickNeighbourhood(n, originalQuery) {
    setScope({ kind: "neighbourhood", neighbourhood: n });
    // rilancia la domanda originale con lo scope quartiere
    setTimeout(() => send(originalQuery), 0);
  }

  return (
    <div className="chat">
      <ScopeBanner scope={scope} onClear={() => setScope(null)} />
      <div className="messages">
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.role === "assistant" && m.intent && (
              <div className="intent">🧭 {m.intent}</div>
            )}
            {m.role === "assistant" && !m.answer ? (
              <div className="dots"><span></span><span></span><span></span></div>
            ) : m.role === "assistant" ? (
              <div className="bubble markdown">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.answer}</ReactMarkdown>
              </div>
            ) : (
              <div className="bubble">{m.text}</div>
            )}
            {m.role === "assistant" && <Details meta={m.meta} />}
          </div>
        ))}
        {showClarify && (
          <div className="clarify">
            {neighbourhoods.map((n) => (
              <button key={n} onClick={() => pickNeighbourhood(n, findLastUser(messages))}>
                {n}
              </button>
            ))}
          </div>
        )}
        <div ref={endRef} />
      </div>
      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
          setInput("");
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Chiedi prezzi, quartieri, recensioni…"
          disabled={busy}
        />
        <button disabled={busy}>Invia</button>
      </form>
    </div>
  );
}

function findLastUser(messages) {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "user") return messages[i].text;
  }
  return "";
}
