import { createContext, useContext, useEffect, useRef, useState } from "react";
import { streamChat } from "./api.js";

// Stato chat condiviso + persistente (sopravvive allo switch di pagina e al reload).
const ChatCtx = createContext(null);

function load(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}

export function ChatProvider({ children }) {
  const [messages, setMessages] = useState(() => load("chat_messages", []));
  const [scope, setScope] = useState(() => load("chat_scope", null));
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);

  useEffect(() => { localStorage.setItem("chat_messages", JSON.stringify(messages)); }, [messages]);
  useEffect(() => { localStorage.setItem("chat_scope", JSON.stringify(scope)); }, [scope]);

  async function send(text, scopeOverride) {
    if (!text.trim() || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setMessages((m) => [...m, { role: "user", text }, { role: "assistant", answer: "", meta: null }]);
    const upLast = (patch) =>
      setMessages((m) => {
        const c = [...m];
        c[c.length - 1] = { ...c[c.length - 1], ...patch(c[c.length - 1]) };
        return c;
      });
    try {
      await streamChat(text, scopeOverride !== undefined ? scopeOverride : scope, {
        onMeta: (meta) => upLast(() => ({ intent: meta.intent, meta })),
        onToken: (t) => upLast((prev) => ({ answer: (prev.answer || "") + t })),
      });
    } catch (e) {
      upLast(() => ({ answer: "Errore: " + e.message }));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  function clearChat() {
    setMessages([]);
  }

  return (
    <ChatCtx.Provider value={{ messages, scope, setScope, busy, send, clearChat }}>
      {children}
    </ChatCtx.Provider>
  );
}

export const useChat = () => useContext(ChatCtx);
