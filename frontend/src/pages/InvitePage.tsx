import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getPublicSnapshot, joinRoom } from "../api/client";
import { AnimatedBackdrop } from "../components/AnimatedBackdrop";
import type { RoomSnapshot } from "../types/events";
import { getIdentity, tokenKey } from "../utils/identity";
import homeStyles from "./HomePage.module.css";
import styles from "./InvitePage.module.css";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Неизвестная ошибка";
}

export function InviteJoin({ code, onJoined }: { code: string; onJoined: (token: string) => void }) {
  const [snapshot, setSnapshot] = useState<RoomSnapshot | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    getPublicSnapshot(code)
      .then((value) => { if (active) setSnapshot(value); })
      .catch((caught) => { if (active) setError(errorMessage(caught)); });
    return () => { active = false; };
  }, [code]);

  const join = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await joinRoom(code, name, getIdentity());
      sessionStorage.setItem(tokenKey("player", code), result.reconnect_token);
      onJoined(result.reconnect_token);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AnimatedBackdrop>
      <div className={styles.inviteColumn}>
        <section className={`${homeStyles.glassCard} ${styles.inviteCard}`}>
          <p className={`${homeStyles.eyebrow} ${styles.inviteEyebrow}`}>Приглашение в комнату</p>

          {!snapshot && !error ? (
            <p className={styles.status}>Проверяем приглашение… Комната {code}</p>
          ) : (
            <>
              <p className={styles.roomCode}>{code}</p>

              {snapshot ? (
                <div className={homeStyles.cardHeading}>
                  <h2>{snapshot.pack.title}</h2>
                  <p>{snapshot.pack.question_count} вопросов · {snapshot.players.length}/5 игроков</p>
                </div>
              ) : null}

              {snapshot?.room.state === "LOBBY" ? (
                <form onSubmit={join} className={styles.inviteForm}>
                  <label className={homeStyles.field}>
                    <input
                      aria-label="Твоё имя"
                      value={name}
                      onChange={(event) => setName(event.target.value.slice(0, 24))}
                      placeholder="Введите имя"
                      required
                    />
                  </label>
                  <button className={homeStyles.primary} disabled={busy}>
                    {busy ? "Входим…" : "Войти в лобби →"}
                  </button>
                </form>
              ) : snapshot ? (
                <p role="alert" className={styles.status}>
                  Игра уже началась — новые игроки войти не могут.
                </p>
              ) : null}

              {error ? (
                <p role="alert" className={styles.status}>{error}</p>
              ) : null}
            </>
          )}

          <Link to="/" className={styles.backLink}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M10 12L6 8L10 4" />
            </svg>
            <span className={styles.btnLabel}>На главную</span>
          </Link>
        </section>
      </div>
    </AnimatedBackdrop>
  );
}
