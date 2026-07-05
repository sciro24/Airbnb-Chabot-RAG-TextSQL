import { Routes, Route, NavLink } from "react-router-dom";
import Home from "./pages/Home.jsx";
import Metrics from "./pages/Metrics.jsx";

export default function App() {
  return (
    <div className="app">
      <nav className="topbar">
        <span className="brand">🏠 Airbnb RAG + Analytics — Roma</span>
        <div className="links">
          <NavLink to="/" end>Esplora</NavLink>
          <NavLink to="/metrics">Osservabilità</NavLink>
        </div>
      </nav>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/metrics" element={<Metrics />} />
      </Routes>
    </div>
  );
}
