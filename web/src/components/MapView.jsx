import { useEffect, useState } from "react";
import { MapContainer, TileLayer, GeoJSON, CircleMarker, Popup } from "react-leaflet";
import { getListings, getGeojson } from "../api.js";

// Palette per colorare i municipi e i punti.
const PALETTE = [
  "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#46f0f0", "#f032e6",
  "#bcf60c", "#008080", "#9a6324", "#800000", "#000075", "#808000", "#e6beff", "#aaffc3",
];

function colorMap(names) {
  const m = {};
  [...names].sort().forEach((n, i) => (m[n] = PALETTE[i % PALETTE.length]));
  return m;
}

export default function MapView({ onSelect }) {
  const [listings, setListings] = useState([]);
  const [geo, setGeo] = useState(null);

  useEffect(() => {
    getListings().then(setListings).catch(() => setListings([]));
    getGeojson().then(setGeo).catch(() => setGeo(null));
  }, []);

  const names = [...new Set(listings.map((l) => l.neighbourhood).filter(Boolean))];
  const colors = colorMap(names);

  return (
    <div className="map-wrap">
      <div className="map-info">{listings.length} annunci con recensioni</div>
      <MapContainer center={[41.9, 12.5]} zoom={11} className="map">
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution="&copy; OpenStreetMap"
        />
        {geo && (
          <GeoJSON
            data={geo}
            style={(f) => ({
              color: "#ffffff",
              weight: 1,
              fillColor: colors[f.properties.neighbourhood] || "#888",
              fillOpacity: 0.12,
            })}
          />
        )}
        {listings.map((l) => (
          <CircleMarker
            key={l.id}
            center={[l.lat, l.lon]}
            radius={5}
            pathOptions={{ color: colors[l.neighbourhood] || "#888", fillOpacity: 0.85 }}
            eventHandlers={{ click: () => onSelect(l) }}
          >
            <Popup>
              <b>{l.name}</b>
              <br />
              {l.neighbourhood} · {l.room_type} · {l.price}€
              <br />
              <button className="popup-btn" onClick={() => onSelect(l)}>
                💬 Chiedi al chatbot
              </button>
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  );
}
