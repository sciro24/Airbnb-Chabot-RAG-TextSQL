import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Send, X, Home, MapPin, Trash2, BarChart3, MessageSquareText } from "lucide-react";
import { useChat } from "../ChatContext.jsx";

// Domande di esempio per dare spunti a chi non sa cosa chiedere.
const EXAMPLES = {
  analytics: {
    icon: <BarChart3 size={15} />,
    title: "Analisi sui dati",
    items: [
      "Qual è il prezzo medio per tipo di stanza?",
      "Prezzo medio all'Eur",
      "Quali sono i 5 quartieri con più annunci?",
      "Prezzo massimo e minimo a Monte Verde",
      "Quanti host hanno più di 5 annunci?",
    ],
  },
  rag: {
    icon: <MessageSquareText size={15} />,
    title: "Recensioni degli ospiti",
    items: [
      "Com'è la zona dell'Eur, è tranquilla?",
      "Gli ospiti si lamentano del rumore?",
      "Cosa dicono le recensioni su pulizia e host?",
      "Le recensioni menzionano la vicinanza ai mezzi?",
    ],
  },
};

function Suggestions({ onPick }) {
  return (
    <div className="suggestions">
      <p className="sugg-intro">Non sai da dove iniziare? Prova una di queste domande:</p>
      {Object.values(EXAMPLES).map((g) => (
        <div key={g.title} className="sugg-group">
          <div className="sugg-title">{g.icon} {g.title}</div>
          <div className="sugg-chips">
            {g.items.map((q) => (
              <button key={q} onClick={() => onPick(q)}>{q}</button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function ScopeBanner({ scope, onClear }) {
  let icon = null, label = "tutta Roma";
  if (scope?.kind === "listing") { icon = <Home size={14} />; label = scope.label; }
  else if (scope?.kind === "neighbourhood") { icon = <MapPin size={14} />; label = scope.neighbourhood; }
  return (
    <div className="scope">
      <span className="scope-label">{icon} Ambito: <b>{label}</b></span>
      {scope && <button className="link" onClick={onClear}><X size={14} /></button>}
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
          <blockquote key={i}><b>{c.neighbourhood}</b> (score {c.score}) — {c.text}</blockquote>
        ))}
      </details>
    );
  }
  return null;
}

export default function Chat({ neighbourhoods }) {
  const { messages, scope, setScope, busy, send, clearChat } = useChat();
  const [input, setInput] = useState("");
  const [showSugg, setShowSugg] = useState(false);
  const endRef = useRef(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const last = messages[messages.length - 1];
  const showClarify = last?.role === "assistant" && last.meta?.clarify;
  const lastUser = [...messages].reverse().find((m) => m.role === "user")?.text || "";

  return (
    <div className="chat">
      <div className="chat-head">
        <ScopeBanner scope={scope} onClear={() => setScope(null)} />
        {messages.length > 0 && (
          <button className="link" title="Svuota chat" onClick={clearChat}><Trash2 size={15} /></button>
        )}
      </div>
      <div className="messages">
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.role === "assistant" && m.intent && <div className="intent">{m.intent}</div>}
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
              <button key={n} onClick={() => { setScope({ kind: "neighbourhood", neighbourhood: n });
                send(lastUser, { kind: "neighbourhood", neighbourhood: n }); }}>
                {n}
              </button>
            ))}
          </div>
        )}
        <div ref={endRef} />
      </div>
      {(messages.length === 0 || showSugg) && (
        <Suggestions onPick={(q) => { send(q); setShowSugg(false); }} />
      )}
      <form className="composer" onSubmit={(e) => { e.preventDefault(); send(input); setInput(""); }}>
        <input value={input} onChange={(e) => setInput(e.target.value)}
          placeholder="Chiedi prezzi, quartieri, recensioni…" disabled={busy} />
        <button type="button" className={`sugg-btn ${showSugg ? "active" : ""}`}
          title="Domande di esempio" onClick={() => setShowSugg((s) => !s)}>/</button>
        <button disabled={busy} title="Invia"><Send size={18} /></button>
      </form>
    </div>
  );
}
