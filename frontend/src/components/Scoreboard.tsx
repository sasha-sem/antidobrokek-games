import { useEffect, useState } from "react";
import { useReducedMotion } from "../hooks/useReducedMotion";
import type { ScoreRow } from "../types/events";
import styles from "./Scoreboard.module.css";

// All rows count up together on the same clock, not one after another —
// reads as a synchronized "counting race" rather than a staggered reveal.
// Linear, not eased: these targets are tiny (0–5-ish), and an eased curve
// squeezed into that few a discrete steps reads as a rushed jump followed
// by a long stall rather than a steady count — linear ticks evenly instead.
// The accuracy/evaluated line only appears once a row's own number has
// finished settling, so it doesn't distract from the count itself.
const COUNT_DURATION_MS = 600;
const COUNT_SETTLE_MS = 300;

function ScoreboardRow({
  row,
  total,
  baseDelayMs,
  countStartDelayMs,
}: {
  row: ScoreRow;
  total?: number;
  baseDelayMs: number;
  countStartDelayMs: number;
}) {
  const reducedMotion = useReducedMotion();
  const [displayScore, setDisplayScore] = useState(reducedMotion ? row.score : 0);
  const [metaVisible, setMetaVisible] = useState(reducedMotion);

  useEffect(() => {
    if (reducedMotion) return;
    let frameId = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const elapsed = now - start - countStartDelayMs;
      const progress = Math.min(1, Math.max(0, elapsed / COUNT_DURATION_MS));
      setDisplayScore(Math.round(row.score * progress));
      if (progress < 1) {
        frameId = requestAnimationFrame(tick);
      } else {
        setMetaVisible(true);
      }
    };
    frameId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frameId);
  }, [row.score, countStartDelayMs, reducedMotion]);

  return (
    <li className={row.rank === 1 ? styles.leader : undefined} style={{ animationDelay: `${baseDelayMs}ms` }}>
      <span className={styles.rank}>{String(row.rank).padStart(2, "0")}</span>
      <span className={styles.name}>
        {row.display_name}
        {/* Always mounted, never conditionally — a row growing taller only
            once its own count finishes (while its neighbors haven't yet)
            is exactly what made the whole table visibly jump. Reserving
            the line's height from the start and only toggling its opacity
            keeps every row's box constant regardless of timing. */}
        {row.accuracy_percent !== undefined ? (
          <small className={styles.meta} data-visible={metaVisible}>
            Точность {row.accuracy_percent}% · оценено {row.evaluated_count ?? 0}
          </small>
        ) : null}
      </span>
      <strong>{displayScore}{total ? `/${total}` : ""}</strong>
    </li>
  );
}

export function Scoreboard({ rows, total, baseDelayMs = 0 }: { rows: ScoreRow[]; total?: number; baseDelayMs?: number }) {
  // Rows all appear together (same animation-delay, not one-by-one) — the
  // count-up starts a beat later, once they've had time to settle in place.
  const countStartDelayMs = baseDelayMs + COUNT_SETTLE_MS;
  return (
    <section className={styles.panel} aria-label="Таблица игроков" style={{ animationDelay: `${baseDelayMs}ms` }}>
      <p className={styles.heading}>Счёт</p>
      {rows.length === 0 ? <p className={styles.empty}>Пока никого</p> : null}
      <ol className={styles.list}>
        {rows.map((row) => (
          <ScoreboardRow key={row.player_id} row={row} total={total} baseDelayMs={baseDelayMs} countStartDelayMs={countStartDelayMs} />
        ))}
      </ol>
    </section>
  );
}
