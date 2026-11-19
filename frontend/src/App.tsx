import { Link, Route, Routes } from "react-router-dom";
import { Empty } from "./components/common";
import { ScanPage } from "./pages/ScanPage";
import { ScansPage } from "./pages/ScansPage";

export function App() {
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">
          Mini Gauntlet
        </Link>
        <span className="muted">Cloud posture scanner</span>
      </header>
      <main className="container">
        <Routes>
          <Route path="/" element={<ScansPage />} />
          <Route path="/scans/:id" element={<ScanPage />} />
          <Route path="*" element={<Empty>Page not found.</Empty>} />
        </Routes>
      </main>
    </>
  );
}
