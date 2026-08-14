import type { ScoreRow } from "../types/events";
import styles from "./Scoreboard.module.css";

export function Scoreboard({ rows, total }: { rows: ScoreRow[]; total?: number }) {
  return (
    <aside className={styles.panel} aria-label="Таблица игроков">
      <details open>
        <summary>Счёт</summary>
        {rows.length === 0 ? <p className={styles.empty}>Пока никого</p> : null}
        <ol className={styles.list}>
          {rows.map((row) => (
            <li key={row.player_id} className={row.rank === 1 ? styles.leader : undefined}>
              <span className={styles.rank}>{row.rank}</span>
              <span className={styles.name}>
                {row.display_name}
                {row.accuracy_percent !== undefined ? <small>Точность {row.accuracy_percent}% · оценено {row.evaluated_count ?? 0}</small> : null}
              </span>
              <strong>{row.score}{total ? `/${total}` : ""}</strong>
            </li>
          ))}
        </ol>
      </details>
    </aside>
  );
}
