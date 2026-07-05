import { Routes, Route, NavLink } from "react-router-dom";
import Home from "./pages/Home.jsx";
import Metrics from "./pages/Metrics.jsx";
import { useTheme } from "./ThemeContext.jsx";

export default function App() {
  const { theme, toggle } = useTheme();
  return (
    <div className="app">
      <nav className="topbar">
        <span className="brand">🏠 Airbnb RAG + Analytics — Roma</span>
        <div className="links">
          <NavLink to="/" end>Esplora</NavLink>
          <NavLink to="/metrics">Osservabilità</NavLink>
          <button className="theme-btn" onClick={toggle} title="Cambia tema">
            {theme === "dark" ? "☀️" : "🌙"}
          </button>
        </div>
      </nav>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/metrics" element={<Metrics />} />
      </Routes>
    </div>
  );
}
