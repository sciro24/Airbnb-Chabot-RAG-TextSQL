import { useEffect, useMemo, useState } from "react";
import { MapContainer, TileLayer, GeoJSON, CircleMarker, Popup, useMap } from "react-leaflet";
import L from "leaflet";
import { getListings, getGeojson } from "../api.js";
import { useTheme } from "../ThemeContext.jsx";

const PALETTE = [
  "#ef476f", "#06d6a0", "#118ab2", "#ffd166", "#8338ec", "#3a86ff", "#fb5607",
  "#ff006e", "#2ec4b6", "#e07a5f", "#9b5de5", "#00bbf9", "#f15bb5", "#43aa8b", "#80ed99",
];
function colorMap(names) {
  const m = {};
  [...names].sort().forEach((n, i) => (m[n] = PALETTE[i % PALETTE.length]));
  return m;
}

const ROME_CENTER = [41.9028, 12.4964];
const ROME_BOUNDS = [
  [41.75, 12.25],
  [42.05, 12.75],
];

function Fit({ feature }) {
  const map = useMap();
  useEffect(() => {
    if (feature) map.fitBounds(L.geoJSON(feature).getBounds(), { padding: [30, 30] });
    else map.setView(ROME_CENTER, 11);
  }, [feature, map]);
  return null;
}

export default function MapView({ onAsk, onNeighbourhood }) {
  const { theme } = useTheme();
  const [listings, setListings] = useState([]);
  const [geo, setGeo] = useState(null);
  const [sel, setSel] = useState("");

  useEffect(() => {
    getListings().then(setListings).catch(() => setListings([]));
    getGeojson().then(setGeo).catch(() => setGeo(null));
  }, []);

  const munNames = useMemo(
    () => (geo ? geo.features.map((f) => f.properties.neighbourhood).sort() : []),
    [geo]
  );
  const colors = colorMap(munNames);
  const selFeature = geo?.features.find((f) => f.properties.neighbourhood === sel) || null;
  const shown = sel ? listings.filter((l) => l.neighbourhood === sel) : listings;

  function changeSel(v) {
    setSel(v);
    onNeighbourhood && onNeighbourhood(v || null);
  }

  const tiles = theme === "dark"
    ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"
    : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png";

  return (
    <div className="map-wrap">
      <div className="map-toolbar">
        <select value={sel} onChange={(e) => changeSel(e.target.value)}>
          <option value="">Tutti i quartieri</option>
          {munNames.map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>
        <span className="map-count">{shown.length} annunci</span>
      </div>
      <MapContainer
        center={ROME_CENTER}
        zoom={11}
        minZoom={10}
        maxBounds={ROME_BOUNDS}
        maxBoundsViscosity={0.9}
        className="map"
        zoomControl={false}
        attributionControl={false}
      >
        <TileLayer url={tiles} subdomains="abcd" />
        {geo && (
          <GeoJSON
            key={(sel || "all") + theme}
            data={geo}
            style={(f) => {
              const active = f.properties.neighbourhood === sel;
              const c = colors[f.properties.neighbourhood] || "#888";
              return {
                color: active ? c : theme === "dark" ? "#3a4150" : "#c7ccd6",
                weight: active ? 2.5 : 1,
                fillColor: c,
                fillOpacity: sel ? (active ? 0.2 : 0.03) : 0.12,
              };
            }}
            onEachFeature={(feature, layer) => {
              // Etichetta col nome del quartiere al centro dell'area
              layer.bindTooltip(feature.properties.neighbourhood, {
                permanent: true, direction: "center", className: "muni-label", opacity: 1,
              });
            }}
          />
        )}
        {shown.map((l) => (
          <CircleMarker
            key={l.id}
            center={[l.lat, l.lon]}
            radius={sel ? 7 : 4}
            pathOptions={{ color: "#fff", weight: 1, fillColor: colors[l.neighbourhood] || "#888", fillOpacity: 0.9 }}
          >
            <Popup>
              <b>{l.name}</b>
              <br />
              {l.neighbourhood} · {l.room_type} · {l.price}€
              <br />
              <button className="popup-btn" onClick={() => onAsk(l)}>💬 Chiedi al chatbot</button>
            </Popup>
          </CircleMarker>
        ))}
        <Fit feature={selFeature} />
      </MapContainer>
    </div>
  );
}
