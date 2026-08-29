import { DragEvent, FormEvent, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { assertNoActiveRoom, closeCurrentRoom, createRoom, joinRoom } from "../api/client";
import { getIdentity, tokenKey } from "../utils/identity";
import { AnimatedBackdrop } from "../components/AnimatedBackdrop";
import { BrandLogo } from "../components/BrandLogo";
import { useFieldErrors } from "../hooks/useFieldErrors";
import { useHoldToConfirm, HOLD_CONFIRM_MS } from "../hooks/useHoldToConfirm";
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
  const [progressLeaving, setProgressLeaving] = useState(false);
  const progressHideTimer = useRef<number | null>(null);
  const hostInFlight = useRef(false);
  const [busy, setBusy] = useState(false);
  // Delayed-true mirror of `busy`, used only for the host button's own
  // "Загрузка… N%" text and the progress bar's visibility — see host().
  const [busyVisible, setBusyVisible] = useState(false);
  const progressShownRef = useRef(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [noticeLeaving, setNoticeLeaving] = useState(false);
  // Mirrors `notice`, read synchronously — dismissNotice() is called from
  // inside a setTimeout closure captured back when the timer was
  // scheduled, so `notice` there would be whatever it was at that render
  // (i.e. stale), not the current value. A ref sidesteps that.
  const noticeTextRef = useRef("");
  const noticeHideTimer = useRef<number | null>(null);
  const noticeDismissTimer = useRef<number | null>(null);
  const [fileActive, setFileActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const joinErrors = useFieldErrors();
  const hostErrors = useFieldErrors();

  // Keep in sync with .rangeThumb's width in HomePage.module.css. The thumb's
  // center is confined to [halfWidth, 100% − halfWidth] instead of straight
  // 0–100%, so at the extremes its edge lands on the track's edge instead of
  // overshooting past it by half its own width.
  const RANGE_THUMB_WIDTH = 34;
  const gracePercent = grace / 15;
  const rangePosition = `calc(${RANGE_THUMB_WIDTH / 2}px + (100% - ${RANGE_THUMB_WIDTH}px) * ${gracePercent})`;

  useEffect(() => {
    return () => {
      if (progressHideTimer.current !== null) window.clearTimeout(progressHideTimer.current);
      if (noticeHideTimer.current !== null) window.clearTimeout(noticeHideTimer.current);
      if (noticeDismissTimer.current !== null) window.clearTimeout(noticeDismissTimer.current);
    };
  }, []);

  // "Комната закрыта" had nothing that ever cleared it — unlike the error
  // toast (superseded by the next action, or read at leisure since it's
  // actionable) a plain confirmation like this should just go away on its
  // own. Fades out, then unmounts once the fade's done, same shape as
  // dismissProgress() below.
  const dismissNotice = () => {
    if (!noticeTextRef.current || noticeHideTimer.current !== null) return;
    setNoticeLeaving(true);
    noticeHideTimer.current = window.setTimeout(() => {
      noticeTextRef.current = "";
      setNotice("");
      setNoticeLeaving(false);
      noticeHideTimer.current = null;
    }, 200);
  };

  // Upload failing after the browser already finished sending the file
  // (server rejects with e.g. "room already exists") or the room getting
  // closed both used to leave the progress bar stuck full — nothing ever
  // reset it. This fades it out first, then clears the underlying state
  // once the fade has actually finished, so it never just vanishes.
  const dismissProgress = () => {
    if (progress === null) return;
    if (!progressShownRef.current) {
      // Debounced away in host() — never actually became visible, so
      // there's nothing to fade out. Clearing it outright (vs. fading)
      // is what keeps a fast rejection from flashing the bar at all.
      setProgress(null);
      return;
    }
    if (progressHideTimer.current !== null) return;
    setProgressLeaving(true);
    progressHideTimer.current = window.setTimeout(() => {
      setProgress(null);
      setProgressLeaving(false);
      progressHideTimer.current = null;
    }, 200);
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

  const join = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!joinErrors.validate(event.currentTarget)) return;
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

  const host = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!hostErrors.validate(event.currentTarget)) return;
    // `busy` state alone isn't enough here — two clicks landing in the same
    // tick both read the same stale (pre-re-render) `busy` value, so both
    // would slip through and run overlapping requests, each toggling
    // `busy`/progress independently on completion (the flicker the button
    // and progress bar showed on a fast double-click). A ref updates
    // synchronously, so the second call sees the first's guard immediately.
    if (!pack || hostInFlight.current) return;
    hostInFlight.current = true;
    setError("");
    setBusy(true);
    // Debounced "busy" UI: don't show "Загрузка…"/the progress bar at all
    // for a request that settles within ~180ms — e.g. the active-room
    // check rejecting instantly on localhost. Something that fast just
    // reads as a flash; only a genuinely slower request earns the visible
    // feedback. progressShownRef records whether the delay actually
    // elapsed, so dismissProgress() knows whether there's anything to
    // fade out afterward.
    progressShownRef.current = false;
    const busyTimer = window.setTimeout(() => {
      progressShownRef.current = true;
      setBusyVisible(true);
    }, 180);
    try {
      // Checked separately, before ever touching `progress` — an active
      // room means this always fails, so there's no real upload to show a
      // progress bar for.
      await assertNoActiveRoom(hostSecret);
      if (progressHideTimer.current !== null) {
        window.clearTimeout(progressHideTimer.current);
        progressHideTimer.current = null;
      }
      setProgressLeaving(false);
      setProgress(0);
      const result = await createRoom(hostSecret, pack, grace, setProgress);
      sessionStorage.setItem(tokenKey("host", result.room_code), result.host_token);
      navigate(result.player_url);
    } catch (caught) {
      setError(errorMessage(caught));
      dismissProgress();
    } finally {
      window.clearTimeout(busyTimer);
      setBusyVisible(false);
      setBusy(false);
      hostInFlight.current = false;
    }
  };

  const closeCurrent = async () => {
    setError("");
    noticeTextRef.current = "";
    setNotice("");
    setNoticeLeaving(false);
    if (noticeHideTimer.current !== null) {
      window.clearTimeout(noticeHideTimer.current);
      noticeHideTimer.current = null;
    }
    if (noticeDismissTimer.current !== null) {
      window.clearTimeout(noticeDismissTimer.current);
      noticeDismissTimer.current = null;
    }
    setBusy(true);
    dismissProgress();
    try {
      await closeCurrentRoom(hostSecret);
      noticeTextRef.current = "Текущая комната закрыта. Теперь можно создать новую игру.";
      setNotice(noticeTextRef.current);
      noticeDismissTimer.current = window.setTimeout(() => {
        noticeDismissTimer.current = null;
        dismissNotice();
      }, 3200);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const { holding: closing, start: startCloseHold, cancel: cancelClose } = useHoldToConfirm(closeCurrent);
  const startClose = () => {
    if (busy || hostSecret.length < 16) return;
    startCloseHold();
  };

  return (
    <AnimatedBackdrop
      overlays={
        <>
          {notice ? (
            <div role="status" className={noticeLeaving ? `${styles.notice} ${styles.noticeLeaving}` : styles.notice}>
              {notice}
            </div>
          ) : null}
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
            <form onSubmit={join} className={styles.joinForm} noValidate>
              <label className={styles.field}>
                <span>Код комнаты</span>
                <input
                  className={styles.codeInput}
                  name="code"
                  value={code}
                  onChange={(e) => {
                    setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 6));
                    joinErrors.clear("code");
                  }}
                  placeholder={joinErrors.invalid.code ? "Заполните это поле" : "KEK4PX"}
                  required
                  minLength={6}
                  data-invalid={joinErrors.invalid.code}
                />
              </label>
              <label className={styles.field}>
                <span>Твоё имя</span>
                <input
                  name="name"
                  value={name}
                  onChange={(e) => {
                    setName(e.target.value.slice(0, 24));
                    joinErrors.clear("name");
                  }}
                  placeholder={joinErrors.invalid.name ? "Заполните это поле" : "Саша"}
                  required
                  data-invalid={joinErrors.invalid.name}
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
            <form onSubmit={host} noValidate>
              <label className={styles.field}>
                <span>Пароль ведущего</span>
                <input
                  type="password"
                  name="hostSecret"
                  value={hostSecret}
                  onChange={(e) => {
                    setHostSecret(e.target.value);
                    hostErrors.clear("hostSecret");
                  }}
                  placeholder={hostErrors.invalid.hostSecret ? "Заполните это поле" : undefined}
                  required
                  data-invalid={hostErrors.invalid.hostSecret}
                />
              </label>
              <label className={styles.file} data-invalid={hostErrors.invalid.pack}>
                <span title={pack?.name}>
                  {hostErrors.invalid.pack ? "Заполните это поле" : pack ? pack.name : "Выбрать dobrokek-pack.zip"}
                </span>
                <small>{pack ? `${(pack.size / 1024 / 1024).toFixed(1)} МБ` : "ZIP до 500 МБ"}</small>
                <input
                  ref={fileInputRef}
                  type="file"
                  name="pack"
                  accept=".zip,application/zip"
                  onChange={(e) => {
                    setPack(e.target.files?.[0] ?? null);
                    hostErrors.clear("pack");
                  }}
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
              {progress !== null && (busyVisible || progressLeaving) ? (
                <div className={progressLeaving ? `${styles.progress} ${styles.progressLeaving}` : styles.progress}>
                  <span style={{ width: `${progress}%` }} />
                </div>
              ) : null}
              <button className={`${styles.primary} ${styles.hostSubmit}`} disabled={busy || !pack}>
                {busyVisible ? `Загрузка… ${progress ?? 0}%` : "Загрузить пак и войти"}
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
                  style={closing ? { transitionDuration: `${HOLD_CONFIRM_MS}ms` } : undefined}
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
