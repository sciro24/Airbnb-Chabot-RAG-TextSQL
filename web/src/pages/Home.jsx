import { useEffect, useState } from "react";
import MapView from "../components/MapView.jsx";
import Chat from "../components/Chat.jsx";
import { getNeighbourhoods } from "../api.js";
import { useChat } from "../ChatContext.jsx";

export default function Home() {
  const { setScope, send } = useChat();
  const [neighbourhoods, setNeighbourhoods] = useState([]);

  useEffect(() => {
    getNeighbourhoods().then(setNeighbourhoods).catch(() => setNeighbourhoods([]));
  }, []);

  // "Chiedi al chatbot" su un annuncio: imposta l'ambito + invia la domanda.
  function askListing(l) {
    const s = { kind: "listing", listing_id: l.id, label: l.name };
    setScope(s);
    send("Cosa dicono gli ospiti di questo alloggio?", s);
  }

  // Dropdown quartiere: allinea l'ambito della chat.
  function pickNeighbourhood(n) {
    if (n) setScope({ kind: "neighbourhood", neighbourhood: n });
    else setScope((s) => (s?.kind === "neighbourhood" ? null : s));
  }

  return (
    <div className="home">
      <section className="intro">
        <h1>Esplora gli alloggi Airbnb di Roma</h1>
        <p>
          Interroga i dati con Analytics (prezzi, quartieri, conteggi) e Recensioni
          (RAG sulle esperienze degli ospiti). Clicca un annuncio sulla mappa o seleziona un
          quartiere per restringere l'ambito, oppure scrivi liberamente nella chat.
        </p>
      </section>
      <div className="split">
        <div className="card map-card">
          <MapView onAsk={askListing} onNeighbourhood={pickNeighbourhood} />
        </div>
        <div className="card chat-card">
          <Chat neighbourhoods={neighbourhoods} />
        </div>
      </div>
    </div>
  );
}
