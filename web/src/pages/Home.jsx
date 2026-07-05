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

  // Click su un annuncio nella mappa: imposta l'ambito + invia una domanda iniziale.
  function selectListing(l) {
    setScope({ kind: "listing", listing_id: l.id, label: l.name });
    setSeed("Cosa dicono gli ospiti di questo alloggio?");
  }

  return (
    <div className="home">
      <section className="intro">
        <h1>Esplora gli alloggi Airbnb di Roma</h1>
        <p>
          Due modi per interrogare i dati: <b>Analytics</b> (prezzi, quartieri, conteggi via
          Text-to-SQL) e <b>Recensioni</b> (RAG semantico sulle recensioni degli ospiti).
          Clicca un <b>punto sulla mappa</b> per chiedere di quello specifico alloggio, oppure
          scrivi liberamente nella chat.
        </p>
      </section>
      <div className="split">
        <div className="left">
          <MapView onSelect={selectListing} />
        </div>
        <div className="right">
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
