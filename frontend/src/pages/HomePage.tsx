import { DragEvent, FormEvent, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { closeCurrentRoom, createRoom, joinRoom } from "../api/client";
import { getIdentity, tokenKey } from "../utils/identity";
import { AnimatedBackdrop } from "../components/AnimatedBackdrop";
import { BrandLogo } from "../components/BrandLogo";
import styles from "./HomePage.module.css";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Неизвестная ошибка";
}

export function HomePage() {
  const navigate = useNavigate();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [showHost, setShowHost] = useState(false);
  const [hostSecret, setHostSecret] = useState("");
  const [pack, setPack] = useState<File | null>(null);
  const [grace, setGrace] = useState(5);
  const [progress, setProgress] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [fileActive, setFileActive] = useState(false);
  const [closing, setClosing] = useState(false);
  const closeTimer = useRef<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const CLOSE_HOLD_MS = 1000;
  // Keep in sync with .rangeThumb's width in HomePage.module.css. The thumb's
  // center is confined to [halfWidth, 100% − halfWidth] instead of straight
  // 0–100%, so at the extremes its edge lands on the track's edge instead of
  // overshooting past it by half its own width.
  const RANGE_THUMB_WIDTH = 34;
  const gracePercent = grace / 15;
  const rangePosition = `calc(${RANGE_THUMB_WIDTH / 2}px + (100% - ${RANGE_THUMB_WIDTH}px) * ${gracePercent})`;

  const cancelClose = () => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
    setClosing(false);
  };

  const startClose = () => {
    if (busy || hostSecret.length < 16 || closeTimer.current !== null) return;
    setClosing(true);
    closeTimer.current = window.setTimeout(() => {
      closeTimer.current = null;
      setClosing(false);
      void closeCurrent();
    }, CLOSE_HOLD_MS);
  };

  const handleCardDragOver = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
  };
  const handleCardDragEnter = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    setFileActive(true);
  };
  const handleCardDragLeave = (event: DragEvent<HTMLElement>) => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setFileActive(false);
    }
  };
  const handleCardDrop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    setFileActive(false);
    const dropped = event.dataTransfer.files?.[0];
    if (!dropped) return;
    setPack(dropped);
    // Dropping outside the native <input type="file"> updates our React
    // state but leaves the input's own .files empty — its "required"
    // validation then blocks submit even though a file is clearly chosen.
    // Assigning a DataTransfer-built FileList is the only way to set an
    // <input type="file">'s files programmatically.
    const input = fileInputRef.current;
    if (input) {
      const transfer = new DataTransfer();
      transfer.items.add(dropped);
      input.files = transfer.files;
    }
  };

  const join = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setBusy(true);
    const normalizedCode = code.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
    try {
      const result = await joinRoom(normalizedCode, name, getIdentity());
      sessionStorage.setItem(tokenKey("player", normalizedCode), result.reconnect_token);
      navigate(`/room/${normalizedCode}`);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const host = async (event: FormEvent) => {
    event.preventDefault();
    if (!pack) return;
    setError("");
    setBusy(true);
    setProgress(0);
    try {
      const result = await createRoom(hostSecret, pack, grace, setProgress);
      sessionStorage.setItem(tokenKey("host", result.room_code), result.host_token);
      navigate(result.player_url);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const closeCurrent = async () => {
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await closeCurrentRoom(hostSecret);
      setNotice("Текущая комната закрыта. Теперь можно создать новую игру.");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AnimatedBackdrop
      overlays={
        <>
          {notice ? <div role="status" className={styles.notice}>{notice}</div> : null}
          {error ? <div role="alert" className={styles.error}>{error}</div> : null}
        </>
      }
    >
      <header className={styles.hero}>
        <p className={styles.eyebrow}>Угадай, кто это прислал</p>
        <h1><BrandLogo className={styles.logoMark} /></h1>
        <p className={styles.tagline}>Один мем. Пять подозреваемых. Ноль шансов остаться серьёзным</p>
      </header>

      <div className={styles.cards}>
        <section className={styles.joinCard}>
          <span className={styles.cardNumber}>01</span>
          <div className={styles.cardBody}>
            <div className={styles.cardHeading}>
              <h2>Присоединиться</h2>
              <p>Введи шестизначный код комнаты</p>
            </div>
            <form onSubmit={join} className={styles.joinForm}>
              <label className={styles.field}>
                <span>Код комнаты</span>
                <input
                  className={styles.codeInput}
                  value={code}
                  onChange={(e) => setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 6))}
                  placeholder="KEK4PX"
                  required
                  minLength={6}
                />
              </label>
              <label className={styles.field}>
                <span>Твоё имя</span>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value.slice(0, 24))}
                  placeholder="Саша"
                  required
                />
              </label>
              <button className={styles.primary} disabled={busy}>
                Войти <span aria-hidden="true">→</span>
              </button>
            </form>
          </div>
        </section>

        <section className={styles.hostEntry}>
          <span className={styles.cardNumber}>02</span>
          <div className={styles.cardHeading}>
            <h2>Создать игру</h2>
            <p>Загрузи свежий ZIP-пак, затем играй вместе со всеми</p>
          </div>
          <button className={styles.secondary} onClick={() => setShowHost((value) => !value)}>
            {showHost ? "Скрыть" : "У меня есть пак"}
          </button>
        </section>

        {showHost ? (
          <section
            className={fileActive ? `${styles.hostCard} ${styles.fileActive}` : styles.hostCard}
            onDragOver={handleCardDragOver}
            onDragEnter={handleCardDragEnter}
            onDragLeave={handleCardDragLeave}
            onDrop={handleCardDrop}
          >
            <form onSubmit={host}>
              <label className={styles.field}>
                <span>Секрет создания игры</span>
                <input type="password" value={hostSecret} onChange={(e) => setHostSecret(e.target.value)} required />
              </label>
              <label className={styles.file}>
                <span title={pack?.name}>{pack ? pack.name : "Выбрать dobrokek-pack.zip"}</span>
                <small>{pack ? `${(pack.size / 1024 / 1024).toFixed(1)} МБ` : "ZIP до 500 МБ"}</small>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".zip,application/zip"
                  onChange={(e) => setPack(e.target.files?.[0] ?? null)}
                  required
                />
              </label>
              <label className={styles.field}>
                <span>Время на ответ после видео: {grace} с</span>
                <div className={styles.rangeWrap}>
                  <input
                    className={styles.rangeInput}
                    type="range"
                    min="0"
                    max="15"
                    value={grace}
                    onChange={(e) => setGrace(Number(e.target.value))}
                  />
                  <div className={styles.rangeTrack}>
                    <div className={styles.rangeFill} style={{ width: rangePosition }} />
                  </div>
                  <div className={styles.rangeThumb} style={{ left: rangePosition }} />
                </div>
              </label>
              {progress !== null ? (
                <div className={styles.progress}>
                  <span style={{ width: `${progress}%` }} />
                </div>
              ) : null}
              <button className={styles.primary} disabled={busy || !pack}>
                {busy ? `Загрузка… ${progress ?? 0}%` : "Загрузить пак и войти"}
              </button>
              <button
                type="button"
                className={styles.closeCurrent}
                disabled={busy || hostSecret.length < 16}
                title="Удерживай, чтобы закрыть"
                onPointerDown={startClose}
                onPointerUp={cancelClose}
                onPointerLeave={cancelClose}
                onPointerCancel={cancelClose}
                onKeyDown={(e) => {
                  if ((e.key === "Enter" || e.key === " ") && !e.repeat) {
                    e.preventDefault();
                    startClose();
                  }
                }}
                onKeyUp={(e) => {
                  if (e.key === "Enter" || e.key === " ") cancelClose();
                }}
              >
                <span
                  className={closing ? `${styles.closeFill} ${styles.closeFillActive}` : styles.closeFill}
                  style={closing ? { transitionDuration: `${CLOSE_HOLD_MS}ms` } : undefined}
                  aria-hidden="true"
                />
                <span className={styles.closeLabel}>Закрыть комнату</span>
              </button>
            </form>
          </section>
        ) : null}
      </div>
    </AnimatedBackdrop>
  );
}
