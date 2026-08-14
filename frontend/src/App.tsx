import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import styles from "./App.module.css";
import { GamePage } from "./pages/GamePage";
import { HomePage } from "./pages/HomePage";

function LegacyHostRedirect() {
  const code = useParams().code ?? "";
  return <Navigate replace to={`/room/${code}`} />;
}

export default function App() {
  return (
    <div className={styles.app}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/room/:code" element={<GamePage role="player" />} />
          <Route path="/host/:code" element={<LegacyHostRedirect />} />
          <Route path="*" element={<HomePage />} />
        </Routes>
      </BrowserRouter>
    </div>
  );
}
