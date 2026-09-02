import { BrowserRouter, Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";
import { PageTransition } from "./components/PageTransition";
import styles from "./App.module.css";
import { GamePage } from "./pages/GamePage";
import { HomePage } from "./pages/HomePage";

function LegacyHostRedirect() {
  const code = useParams().code ?? "";
  return <Navigate replace to={`/room/${code}`} />;
}

// `location` is passed to <Routes> explicitly rather than left ambient:
// PageTransition freezes whichever children it was given at the moment
// the key changes and keeps rendering exactly that until its exit
// animation finishes, so the outgoing route needs its OWN location baked
// into its element rather than reading the router's (already-updated)
// current one — otherwise the "old" screen would immediately re-render
// as the new route mid-exit.
function AnimatedRoutes() {
  const location = useLocation();
  return (
    <PageTransition transitionKey={location.pathname}>
      <Routes location={location}>
        <Route path="/" element={<HomePage />} />
        <Route path="/room/:code" element={<GamePage role="player" />} />
        <Route path="/host/:code" element={<LegacyHostRedirect />} />
        <Route path="*" element={<HomePage />} />
      </Routes>
    </PageTransition>
  );
}

export default function App() {
  return (
    <div className={styles.app}>
      <BrowserRouter>
        <AnimatedRoutes />
      </BrowserRouter>
    </div>
  );
}
