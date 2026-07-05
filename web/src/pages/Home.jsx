import { useEffect, useState } from "react";
import MapView from "../components/MapView.jsx";
import Chat from "../components/Chat.jsx";
import { getNeighbourhoods } from "../api.js";

export default function Home() {
  const [scope, setScope] = useState(null);
  const [seed, setSeed] = useState(null);
  const [neighbourhoods, setNeighbourhoods] = useState([]);

  useEffect(() => {
    getNeighbourhoods().then(setNeighbourhoods).catch(() => setNeighbourhoods([]));
  }, []);

  // "Chiedi al chatbot" su un annuncio: imposta l'ambito + invia la domanda iniziale.
  // (il semplice click sul marker apre solo il popup, non invia nulla)
  function askListing(l) {
    setScope({ kind: "listing", listing_id: l.id, label: l.name });
    setSeed("Cosa dicono gli ospiti di questo alloggio?");
  }

  // Dropdown quartiere sulla mappa: allinea l'ambito della chat.
  function pickNeighbourhood(n) {
    if (n) setScope({ kind: "neighbourhood", neighbourhood: n });
    else setScope((s) => (s?.kind === "neighbourhood" ? null : s));
  }

  return (
    <div className="home">
      <section className="intro">
        <h1>Esplora gli alloggi Airbnb di Roma</h1>
        <p>
          Interroga i dati con <b>Analytics</b> (prezzi, quartieri, conteggi) e <b>Recensioni</b>
          (RAG sulle esperienze degli ospiti). Clicca un <b>punto sulla mappa</b> o seleziona un
          <b> quartiere</b> per restringere l'ambito, oppure scrivi liberamente nella chat.
        </p>
      </section>
      <div className="split">
        <div className="card map-card">
          <MapView onAsk={askListing} onNeighbourhood={pickNeighbourhood} />
        </div>
        <div className="card chat-card">
          <Chat
            scope={scope}
            setScope={setScope}
            neighbourhoods={neighbourhoods}
            seed={seed}
            onSeedConsumed={() => setSeed(null)}
          />
        </div>
      </div>
    </div>
  );
}
