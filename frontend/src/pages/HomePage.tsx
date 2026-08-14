import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { closeCurrentRoom, createRoom, joinRoom } from "../api/client";
import { getIdentity, tokenKey } from "../utils/identity";
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
    if (!window.confirm("Закрыть текущую комнату? Подключённые игроки будут отключены.")) return;
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
    <main className={styles.page}>
      <header className={styles.hero}>
        <p className={styles.eyebrow}>Угадай, кто это прислал</p>
        <h1>Доброкек<span>.</span></h1>
        <p>Один мем. Пять подозреваемых. Ноль шансов остаться серьёзным.</p>
      </header>

      <section className={styles.joinCard}>
        <div className={styles.cardTitle}>
          <span>01</span>
          <div><h2>Присоединиться</h2><p>Введи шестизначный код комнаты</p></div>
        </div>
        <form onSubmit={join} className={styles.joinForm}>
          <label>Код комнаты<input aria-label="Код комнаты" value={code} onChange={(e) => setCode(e.target.value.toUpperCase().slice(0, 6))} placeholder="KEK4PX" required minLength={6} /></label>
          <label>Твоё имя<input aria-label="Твоё имя" value={name} onChange={(e) => setName(e.target.value.slice(0, 24))} placeholder="Саша" required /></label>
          <button className={styles.primary} disabled={busy}>Войти <span>→</span></button>
        </form>
      </section>

      <section className={styles.hostEntry}>
        <span>02</span>
        <div><h2>Создать игру</h2><p>Загрузи свежий ZIP-пак, затем играй вместе со всеми</p></div>
        <button className={styles.secondary} onClick={() => setShowHost((value) => !value)}>{showHost ? "Скрыть" : "У меня есть пак"}</button>
      </section>

      {showHost ? (
        <section className={styles.hostCard}>
          <form onSubmit={host}>
            <label>Секрет создания игры<input type="password" value={hostSecret} onChange={(e) => setHostSecret(e.target.value)} required /></label>
            <label className={styles.file}>
              <span>{pack ? pack.name : "Выбрать dobrokek-pack.zip"}</span>
              <small>{pack ? `${(pack.size / 1024 / 1024).toFixed(1)} МБ` : "ZIP до 500 МБ"}</small>
              <input type="file" accept=".zip,application/zip" onChange={(e) => setPack(e.target.files?.[0] ?? null)} required />
            </label>
            <label>Время на ответ после видео: {grace} с<input type="range" min="0" max="15" value={grace} onChange={(e) => setGrace(Number(e.target.value))} /></label>
            {progress !== null ? <div className={styles.progress}><span style={{ width: `${progress}%` }} /></div> : null}
            <button className={styles.primary} disabled={busy || !pack}>{busy ? `Загрузка… ${progress ?? 0}%` : "Загрузить пак и войти"}</button>
            <button type="button" className={styles.closeCurrent} disabled={busy || hostSecret.length < 16} onClick={closeCurrent}>Закрыть текущую комнату</button>
          </form>
        </section>
      ) : null}
      {notice ? <div role="status" className={styles.notice}>{notice}</div> : null}
      {error ? <div role="alert" className={styles.error}>{error}</div> : null}
    </main>
  );
}
