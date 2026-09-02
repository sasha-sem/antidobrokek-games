import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { Link, useParams } from "react-router-dom";
import { AnimatedBackdrop } from "../components/AnimatedBackdrop";
import { PageTransition } from "../components/PageTransition";
import { useAutoDismiss } from "../hooks/useAutoDismiss";
import { useHoldToConfirm, HOLD_CONFIRM_MS } from "../hooks/useHoldToConfirm";
import { useIdleVisibility } from "../hooks/useIdleVisibility";
import { useLoopingBackgroundVideo } from "../hooks/useLoopingBackgroundVideo";
import { useRoomSocket } from "../hooks/useRoomSocket";
import { useSynchronizedPlayback } from "../hooks/useSynchronizedPlayback";
import type { Author, CurrentQuestion, RoomSnapshot, ScoreRow, ServerEnvelope } from "../types/events";
import { tokenKey } from "../utils/identity";
import { FinishedScreen } from "./FinishedScreen";
import { InviteJoin } from "./InvitePage";
import backdropStyles from "../components/AnimatedBackdrop.module.css";
import homeStyles from "./HomePage.module.css";
import styles from "./GamePage.module.css";

// Keep in sync with .volumeThumb's width in GamePage.module.css — same
// centering trick as HomePage's own RANGE_THUMB_WIDTH.
const VOLUME_THUMB_WIDTH = 16;

const VOLUME_STORAGE_KEY = "dobrokek.playerVolume";
const MUTED_STORAGE_KEY = "dobrokek.playerMuted";

function readPersistedVolume(): number {
  try {
    const raw = localStorage.getItem(VOLUME_STORAGE_KEY);
    if (raw === null) return 1;
    const value = Number(raw);
    return Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 1;
  } catch {
    return 1;
  }
}

function writePersistedVolume(value: number) {
  try {
    localStorage.setItem(VOLUME_STORAGE_KEY, String(value));
  } catch {
    // Best-effort only — see writePersistedPlaying in useLoopingBackgroundVideo.
  }
}

function readPersistedMuted(): boolean {
  try {
    return localStorage.getItem(MUTED_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function writePersistedMuted(value: boolean) {
  try {
    localStorage.setItem(MUTED_STORAGE_KEY, value ? "1" : "0");
  } catch {
    // Best-effort only.
  }
}

interface RevealPayload {
  correct_author: Author;
  correct_count: number;
  selected_author_id?: string | null;
  is_correct?: boolean;
  scoreboard: ScoreRow[];
  next_question_at?: string;
}

function Connection({ code, role, token }: { code: string; role: "host" | "player"; token: string }) {
  const [snapshot, setSnapshot] = useState<RoomSnapshot | null>(null);
  const [reveal, setReveal] = useState<RevealPayload | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [reaction, setReaction] = useState<-1 | 1 | null>(null);
  const [accepted, setAccepted] = useState(false);
  const [mediaReady, setMediaReady] = useState(new Set<string>());
  const error = useAutoDismiss();
  const fullscreenTip = useAutoDismiss();
  const [videoError, setVideoError] = useState(false);
  const [copied, setCopied] = useState(false);
  const [ownPlayerId, setOwnPlayerId] = useState<string | null>(null);
  const [muted, setMuted] = useState(() => readPersistedMuted());
  const [volume, setVolume] = useState(() => readPersistedVolume());
  const [now, setNow] = useState(Date.now());
  const videoRef = useRef<HTMLVideoElement>(null);
  const readyQuestion = useRef("");
  // The volume to restore to when unmuting via the icon (not the slider's
  // own value, which drops to 0 while muted — see the sound toggle/slider
  // handlers below).
  const lastVolumeRef = useRef(volume > 0 ? volume : 1);
  // Unlike Home/Invite/Lobby (AnimatedBackdrop's own instance of this
  // hook), this screen always arrives with the background easing to a
  // stop, and toggling it here is local to this visit — it never reads or
  // writes the shared play/pause preference those screens share.
  const { videoRef: bgVideoRef, playing: bgPlaying, toggle: toggleBg } = useLoopingBackgroundVideo({ persist: false });

  const onEvent = useCallback((event: ServerEnvelope) => {
    const payload = event.payload as Record<string, unknown>;
    if (event.type === "authenticated") {
      setOwnPlayerId((payload.player_id as string | null) ?? null);
    } else if (event.type === "room_snapshot") {
      const next = payload as unknown as RoomSnapshot;
      setSnapshot(next);
      setSelected(next.current_question?.selected_author_id ?? null);
      setReaction(next.current_question?.reaction ?? null);
      setReveal(next.current_question?.correct_author ? {
        correct_author: next.current_question.correct_author,
        correct_count: 0,
        selected_author_id: next.current_question.selected_author_id,
        is_correct: next.current_question.is_correct,
        scoreboard: next.scoreboard,
      } : null);
    } else if (event.type === "question_preload") {
      const question = payload as unknown as CurrentQuestion;
      setReveal(null);
      setSelected(null);
      setReaction(null);
      setAccepted(false);
      setVideoError(false);
      readyQuestion.current = "";
      setMediaReady(new Set());
      setSnapshot((previous) => previous ? {
        ...previous,
        room: { ...previous.room, state: "PRELOADING", current_position: question.position },
        current_question: question,
      } : previous);
    } else if (event.type === "question_started") {
      setSnapshot((previous) => previous?.current_question ? {
        ...previous,
        room: { ...previous.room, state: "QUESTION" },
        current_question: {
          ...previous.current_question,
          starts_at: String(payload.starts_at),
          ends_at: String(payload.ends_at),
          grace_seconds: Number(payload.grace_seconds ?? 0),
        },
      } : previous);
    } else if (event.type === "answer_accepted") {
      setSelected(String(payload.selected_author_id));
      setAccepted(true);
    } else if (event.type === "question_revealed") {
      const value = payload as unknown as RevealPayload;
      setReveal(value);
      setSelected(value.selected_author_id ?? selected);
      setSnapshot((previous) => previous ? {
        ...previous,
        room: { ...previous.room, state: "REVEAL" },
        scoreboard: value.scoreboard,
        current_question: previous.current_question ? { ...previous.current_question, correct_author: value.correct_author } : undefined,
      } : previous);
    } else if (event.type === "scoreboard_updated") {
      setSnapshot((previous) => previous ? { ...previous, scoreboard: payload.scoreboard as ScoreRow[] } : previous);
    } else if (event.type === "reaction_accepted") {
      setReaction((payload.value as -1 | 1 | null) ?? null);
    } else if (event.type === "player_media_ready") {
      setMediaReady((previous) => new Set(previous).add(String(payload.player_id)));
    } else if (event.type === "player_connection_changed") {
      setSnapshot((previous) => previous ? {
        ...previous,
        players: previous.players.map((item) => item.id === payload.player_id ? {
          ...item,
          is_connected: Boolean(payload.is_connected),
        } : item),
      } : previous);
    } else if (event.type === "game_finished") {
      setSnapshot((previous) => previous ? {
        ...previous,
        room: { ...previous.room, state: "FINISHED" },
        scoreboard: payload.scoreboard as ScoreRow[],
        popular_meme: payload.popular_meme as RoomSnapshot["popular_meme"],
      } : previous);
    } else if (event.type === "player_kicked") {
      error.show("Ведущий удалил вас из комнаты");
    } else if (event.type === "room_state_changed" && payload.state === "CLOSED") {
      error.show("Ведущий закрыл комнату");
    } else if (event.type === "error") {
      error.show(String(payload.message ?? "Ошибка игрового сервера"));
    }
  }, [selected, error.show]);

  const { status, serverOffsetMs, send } = useRoomSocket(code, role, token, onEvent);
  const question = snapshot?.current_question;
  const state = snapshot?.room.state;

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 200);
    return () => window.clearInterval(timer);
  }, []);

  // One-time check on a delay, not immediately on mount and not a live
  // fullscreenchange listener — the lobby is only ever shown once per
  // room's lifetime, so there's no later moment this needs to react to;
  // it just shouldn't fire the instant the page loads, before the player
  // has even seen the room.
  //
  // document.fullscreenElement alone isn't enough: F11 toggles the
  // browser's OWN chrome (hides tabs/address bar), not the JS Fullscreen
  // API — pressing it never sets fullscreenElement at all, in any
  // browser, so that check alone still showed the tip to someone already
  // fullscreen via F11 after a reload (a reload itself doesn't exit F11
  // the way it exits a requestFullscreen() call). There's no direct API
  // for "is F11 active", so this approximates it: an F11'd window's
  // viewport fills the entire screen height (no title bar, no taskbar);
  // an ordinary maximized window still leaves room for those.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      // Guarded, not a bare size comparison: a tab that isn't actually
      // being rendered right now (backgrounded) can report innerHeight
      // and screen.height as both 0, which would otherwise satisfy "fills
      // the screen" by coincidence and wrongly read as fullscreen.
      const sizesLookValid = window.innerHeight > 100 && screen.height > 0;
      const alreadyFullscreen =
        Boolean(document.fullscreenElement) ||
        (sizesLookValid && screen.height - window.innerHeight <= 4);
      if (!alreadyFullscreen) {
        fullscreenTip.show("Для полного погружения включите полноэкранный режим (F11)");
      }
    }, 5000);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keeps the actual <video> volume in sync with the persisted/adjusted
  // level — .volume isn't a reflected HTML attribute like `muted`, so a
  // freshly mounted (or freshly loaded) video element doesn't pick up
  // anything other than the browser's own default (1.0) on its own.
  useEffect(() => {
    if (videoRef.current) videoRef.current.volume = volume;
  }, [volume, question?.media_url]);

  const {
    autoplayMuted,
    clearAutoplayMuted,
    playbackBlocked,
    resumePlayback,
  } = useSynchronizedPlayback({
    active: state === "QUESTION",
    question,
    serverOffsetMs,
    setMuted,
    videoRef,
  });

  const authors = question?.authors ?? [];
  useEffect(() => {
    if (role !== "player" || state !== "QUESTION") return;
    const listener = (event: KeyboardEvent) => {
      if (/^[1-9]$/.test(event.key)) {
        const author = authors[Number(event.key) - 1];
        if (author) send("answer_submit", { author_id: author.id });
      }
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [authors, role, send, state]);

  const countdown = useMemo(() => {
    if (!question?.ends_at) return null;
    const deadline = new Date(question.ends_at).getTime() + (question.grace_seconds ?? 0) * 1000;
    return Math.max(0, Math.ceil((deadline - (now + serverOffsetMs)) / 1000));
  }, [now, question?.ends_at, question?.grace_seconds, serverOffsetMs]);

  const revealCountdown = useMemo(() => {
    if (!reveal?.next_question_at) return null;
    return Math.max(0, Math.ceil((new Date(reveal.next_question_at).getTime() - (now + serverOffsetMs)) / 1000));
  }, [now, reveal?.next_question_at, serverOffsetMs]);

  // Derived from the same server-synced clock as `countdown` (not the
  // video element's own `timeupdate`) so it can't visibly diverge from
  // what useSynchronizedPlayback is actually driving the video toward —
  // buffering stalls the video, not this.
  const videoProgress = useMemo(() => {
    if (state !== "QUESTION" || !question?.starts_at) return 0;
    const startsAt = new Date(question.starts_at).getTime();
    const elapsedMs = now + serverOffsetMs - startsAt;
    return Math.max(0, Math.min(1, elapsedMs / question.duration_ms));
  }, [state, now, serverOffsetMs, question?.starts_at, question?.duration_ms]);

  // The sound toggle/volume slider fade during idle playback like a real
  // player's chrome — active whenever a clip is actually up (QUESTION or
  // REVEAL), woken by pointer activity over the stage (wired below).
  const soundVisibility = useIdleVisibility(state === "QUESTION" || state === "REVEAL");

  // Slider's displayed position, not raw `volume` state: shows 0 while
  // muted (regardless of what volume it'll restore to), the actual volume
  // otherwise — same "value vs. display" split HomePage's grace-period
  // slider doesn't need but this one does, since mute is a second axis on
  // top of the same control.
  //
  // `autoplayMuted` is excluded from that collapse on purpose: every fresh
  // page load starts muted because the browser requires a real gesture
  // before it'll autoplay with sound (useSynchronizedPlayback forces
  // `setMuted(true)` for exactly this reason, not because the player
  // asked for it) — showing 0 there made a correctly-restored, nonzero
  // saved volume look like it had reset to 0 on every reload. The slider
  // still shows the level sound will resume at the moment they unmute.
  // Same reasoning applies to the icon glyph and its label: a mute forced
  // by the autoplay policy isn't something the player did, so the icon
  // shouldn't claim they turned sound off. The "click to enable sound"
  // hint stays regardless (autoplayMuted alone still drives that) — audio
  // genuinely is silent until they click, that part's accurate either way.
  const displayMuted = muted && !autoplayMuted;
  const displayVolume = displayMuted ? 0 : volume;
  const volumePosition = `calc(${VOLUME_THUMB_WIDTH / 2}px + (100% - ${VOLUME_THUMB_WIDTH}px) * ${displayVolume})`;

  const mediaLoaded = () => {
    if (state !== "PRELOADING" || !question) return;
    const key = `${question.position}:${question.media_url}`;
    if (readyQuestion.current === key) return;
    readyQuestion.current = key;
    if (role === "player") send("player_media_ready");
  };

  // A browser won't autoplay-with-sound video that no click ever primed —
  // and the round's video is started by a server-scheduled timer, not a
  // click. This "plays" a silent 0.01s tone to spend that one required
  // gesture ahead of time, riding on whatever click the player makes next
  // (here, "Готов") rather than needing a click of its own. Best-effort: if
  // it fails, the question screen's own muted-autoplay-then-manual-unmute
  // fallback (autoplayMuted) still covers it, so nothing here blocks ready.
  const primeAudioUnlock = async () => {
    try {
      const AudioContextClass = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      if (!AudioContextClass) return;
      const context = new AudioContextClass();
      await context.resume();
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      gain.gain.value = 0;
      oscillator.connect(gain);
      gain.connect(context.destination);
      oscillator.start();
      oscillator.stop(context.currentTime + 0.01);
    } catch {
      // Silently ignored — see comment above.
    }
  };

  // Set the instant the hold completes, ahead of the server's confirmation
  // round-trip. Without this, `readying` (which drops to false the moment
  // the hold timer fires) would let the fill's clip-path snap back to
  // empty for the gap before `room_snapshot` confirms is_ready — a visible
  // flash-back right before the button crossfades into the "done" text.
  const [justReadied, setJustReadied] = useState(false);
  const markReady = () => {
    void primeAudioUnlock();
    setJustReadied(true);
    send("player_ready", { ready: true });
  };
  // Marking ready is effectively one-way through this UI (no "unready"
  // control) and, once every connected player has done it, starts the
  // game immediately — including with just one player, if they're alone
  // in the room. A hold, not a tap, matches how consequential that is.
  const { holding: readying, start: startReady, cancel: cancelReady } = useHoldToConfirm(markReady);
  const readyFilled = readying || justReadied;

  const copyInvite = async () => {
    const invite = `${location.origin}/room/${code}`;
    try {
      await navigator.clipboard.writeText(invite);
    } catch {
      const field = document.createElement("textarea");
      field.value = invite;
      field.style.position = "fixed";
      field.style.opacity = "0";
      document.body.appendChild(field);
      field.select();
      document.execCommand("copy");
      field.remove();
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  if (!snapshot) {
    return (
      <PageTransition transitionKey="connecting">
        <main className={styles.center}><div className={styles.loader} /><h1>Подключаемся</h1><p>{status === "reconnecting" ? "Сеть прервалась, пытаемся снова" : `Комната ${code}`}</p>{error.text ? <p className={styles.error}>{error.text}</p> : null}</main>
      </PageTransition>
    );
  }

  const connectedCount = snapshot.players.filter((item) => item.is_connected).length;
  const ownPlayer = snapshot.players.find((item) => item.id === ownPlayerId);

  if (state === "FINISHED") {
    return <FinishedScreen snapshot={snapshot} role={role} onCloseRoom={() => send("host_close_room")} />;
  }

  if (state === "LOBBY") {
    return (
      <PageTransition transitionKey="lobby">
      <AnimatedBackdrop
        overlays={
          <>
            <div className={styles.connectionBadge} data-status={status} role="status">
              {status === "connected" ? "В сети" : "Переподключение…"}
            </div>
            {error.text ? (
              <div
                role="alert"
                className={
                  error.leaving
                    ? `${homeStyles.toast} ${homeStyles.toastError} ${homeStyles.toastLeaving}`
                    : `${homeStyles.toast} ${homeStyles.toastError}`
                }
                onClick={() => error.dismiss()}
              >
                {error.text}
              </div>
            ) : null}
            {fullscreenTip.text ? (
              <div
                role="status"
                className={
                  fullscreenTip.leaving
                    ? `${homeStyles.toast} ${styles.fullscreenToast} ${homeStyles.toastLeaving}`
                    : `${homeStyles.toast} ${styles.fullscreenToast}`
                }
                onClick={() => fullscreenTip.dismiss()}
              >
                Для полного погружения включите полноэкранный режим (<strong>F11</strong>)
              </div>
            ) : null}
          </>
        }
      >
        <section className={`${homeStyles.glassCard} ${styles.lobbyHero}`}>
          <p className={`${homeStyles.eyebrow} ${styles.lobbyEyebrow}`}>{snapshot.pack.title}</p>
          <h1 className={styles.lobbyCode}>{code}</h1>
          <button type="button" className={styles.copyButton} data-copied={copied} onClick={copyInvite}>
            <span className={styles.copyIconStack} aria-hidden="true">
              <svg className={styles.copyIconDefault} width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" stroke="currentColor" strokeWidth="1.4" />
                <path d="M3.5 10.5H2.5C1.94772 10.5 1.5 10.0523 1.5 9.5V2.5C1.5 1.94772 1.94772 1.5 2.5 1.5H9.5C10.0523 1.5 10.5 1.94772 10.5 2.5V3.5" stroke="currentColor" strokeWidth="1.4" />
              </svg>
              <svg className={styles.copyIconCheck} width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M3 8.5L6.2 11.5L13 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            <span className={styles.copyLabel}>{copied ? "Скопировано" : "Скопировать приглашение"}</span>
          </button>
          <p className={styles.lobbyMeta}>{snapshot.pack.question_count} вопросов · {snapshot.players.length}/5 игроков</p>
        </section>

        <div className={styles.playerGrid}>
          {snapshot.players.map((item, index) => (
            <article
              key={item.id}
              className={styles.playerCard}
              data-connected={item.is_connected}
              data-ready={item.is_ready}
              style={{ transitionDelay: `${Math.min(index, 4) * 40}ms` }}
            >
              <b className={styles.playerNumber}>{String(index + 1).padStart(2, "0")}</b>
              <h2 className={styles.playerName}>{item.display_name}</h2>
              <span className={styles.playerStatus} data-connected={item.is_connected} data-ready={item.is_ready}>
                {item.is_connected ? (item.is_ready ? "Готов" : "Не готов") : "Не в сети"}
              </span>
              {role === "host" ? (
                <button className={styles.kickButton} onClick={() => send("host_kick_player", { player_id: item.id })} aria-label={`Удалить ${item.display_name}`}>
                  ×
                </button>
              ) : null}
            </article>
          ))}
          {Array.from({ length: Math.max(0, 5 - snapshot.players.length) }, (_, index) => (
            <article key={`empty-${index}`} className={`${styles.playerCard} ${styles.emptySlot}`}>
              <b className={styles.playerNumber}>{String(snapshot.players.length + index + 1).padStart(2, "0")}</b>
              <span className={styles.emptyLabel}>Свободно</span>
            </article>
          ))}
        </div>

        <section className={styles.lobbyAction}>
          {role === "player" ? (
            <>
              <div className={styles.readySlot} data-ready={Boolean(ownPlayer?.is_ready)}>
                <button
                  type="button"
                  className={styles.readyButton}
                  data-holding={readyFilled}
                  disabled={Boolean(ownPlayer?.is_ready)}
                  onPointerDown={startReady}
                  onPointerUp={cancelReady}
                  onPointerLeave={cancelReady}
                  onPointerCancel={cancelReady}
                  onKeyDown={(e) => {
                    if ((e.key === "Enter" || e.key === " ") && !e.repeat) {
                      e.preventDefault();
                      startReady();
                    }
                  }}
                  onKeyUp={(e) => {
                    if (e.key === "Enter" || e.key === " ") cancelReady();
                  }}
                >
                  <span
                    className={readyFilled ? `${styles.readyFill} ${styles.readyFillActive}` : styles.readyFill}
                    style={{ "--hold-confirm-ms": `${HOLD_CONFIRM_MS}ms` } as CSSProperties}
                    aria-hidden="true"
                  />
                  <span className={styles.readyLabel}>Приготовиться</span>
                </button>
                <p className={styles.readyDone}>Готово — ждём остальных</p>
              </div>
              <p className={styles.lobbyHint}>
                {ownPlayer?.is_ready
                  ? "Игра начнётся автоматически, когда все подключённые игроки будут готовы"
                  : "Дождись друзей — игра начнётся сразу, как только приготовишься"}
              </p>
            </>
          ) : (
            <>
              <button className={homeStyles.primary} disabled={!snapshot.players.length || snapshot.players.some((item) => item.is_connected && !item.is_ready)} onClick={() => send("host_start_game")}>
                Начать игру
              </button>
              <button className={styles.lobbyDanger} onClick={() => send("host_close_room")}>Закрыть</button>
            </>
          )}
        </section>
      </AnimatedBackdrop>
      </PageTransition>
    );
  }

  return (
    <PageTransition transitionKey="game">
    <main className={styles.game}>
      <video
        ref={bgVideoRef}
        className={backdropStyles.bgVideo}
        autoPlay
        muted
        loop
        playsInline
        preload="auto"
        src="/bg.mp4"
      />
      <div className={backdropStyles.bgOverlayVignette} />
      <div className={backdropStyles.bgOverlayDim} />
      <button
        type="button"
        className={backdropStyles.pauseButton}
        data-playing={bgPlaying}
        onClick={toggleBg}
        aria-label={bgPlaying ? "Остановить фон" : "Запустить фон"}
      >
        <span className={backdropStyles.pauseIcon} aria-hidden="true">
          <svg className={backdropStyles.pauseIconGlyph} data-variant="pause" width="8.5" height="10.2" viewBox="0 0 10 12" fill="currentColor">
            <rect x="0" width="3" height="12" rx="1" />
            <rect x="7" width="3" height="12" rx="1" />
          </svg>
          <svg className={backdropStyles.pauseIconGlyph} data-variant="play" width="8.5" height="10.2" viewBox="0 0 10 12" fill="currentColor">
            <polygon points="0,0 10,6 0,12" />
          </svg>
        </span>
        <span className={backdropStyles.pauseLabel} aria-hidden="true">{bgPlaying ? "стоп" : "пуск"}</span>
      </button>

      <div className={styles.gameContent}>
      <header
        className={styles.gameHeader}
        style={{ backgroundSize: `${(state === "QUESTION" ? videoProgress : 0) * 100}% 100%` }}
      >
        <strong>Вопрос {question?.position ?? "—"}/{snapshot.pack.question_count}</strong>
        <div className={styles.timer} data-low={countdown !== null && countdown <= 3}>{state === "PRELOADING" ? "Загрузка" : state === "REVEAL" ? "Ответ" : `${countdown ?? "—"} с`}</div>
        <span>Комната {code}</span>
      </header>
      <section className={styles.gameGrid}>
        <div className={styles.stage} onPointerMove={soundVisibility.wake} onPointerDown={soundVisibility.wake}>
          {question ? (
            <video
              ref={videoRef}
              src={question.media_url}
              playsInline
              preload="auto"
              muted={muted}
              onCanPlay={mediaLoaded}
              onError={() => setVideoError(true)}
              onContextMenu={(event) => event.preventDefault()}
            />
          ) : null}
          {question ? (
            <div className={styles.soundControls} data-visible={soundVisibility.visible}>
              <button
                type="button"
                className={styles.soundToggle}
                data-muted={displayMuted}
                aria-label={displayMuted ? "Включить звук" : "Выключить звук"}
                onClick={() => {
                  if (!muted) {
                    setMuted(true);
                    writePersistedMuted(true);
                    if (videoRef.current) videoRef.current.muted = true;
                    return;
                  }
                  const restored = volume > 0 ? volume : lastVolumeRef.current;
                  setVolume(restored);
                  setMuted(false);
                  writePersistedVolume(restored);
                  writePersistedMuted(false);
                  if (videoRef.current) {
                    videoRef.current.volume = restored;
                    videoRef.current.muted = false;
                  }
                  clearAutoplayMuted();
                  void videoRef.current?.play();
                }}
              >
                <span className={styles.soundIconStack} aria-hidden="true">
                  <svg className={styles.soundIconOn} width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M11 5L6 9H2v6h4l5 4V5z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
                    <path d="M15.5 8.5a5 5 0 0 1 0 7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                    <path d="M19 5a10 10 0 0 1 0 14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                  </svg>
                  <svg className={styles.soundIconMuted} width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M11 5L6 9H2v6h4l5 4V5z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
                    <path d="M23 9l-6 6M17 9l6 6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                  </svg>
                </span>
              </button>
              <div className={styles.volumeWrap}>
                <input
                  className={styles.volumeInput}
                  aria-label="Громкость"
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={displayVolume}
                  onChange={(event) => {
                    const next = Number(event.target.value);
                    setVolume(next);
                    writePersistedVolume(next);
                    if (next > 0) lastVolumeRef.current = next;
                    const nextMuted = next === 0;
                    setMuted(nextMuted);
                    writePersistedMuted(nextMuted);
                    if (videoRef.current) {
                      videoRef.current.volume = next;
                      videoRef.current.muted = nextMuted;
                    }
                    if (!nextMuted) clearAutoplayMuted();
                  }}
                />
                <div className={styles.volumeTrack}>
                  <div className={styles.volumeFill} style={{ width: volumePosition }} />
                </div>
                <div className={styles.volumeThumb} style={{ left: volumePosition }} />
              </div>
              {autoplayMuted ? <span className={styles.soundHint}>Нажми, чтобы включить звук</span> : null}
            </div>
          ) : null}
          {state === "PRELOADING" ? (
            <div className={styles.overlay}>
              <div className={styles.loader} />
              <h2>Готовим мем</h2>
              <p>{role === "host" ? `${mediaReady.size}/${connectedCount} игроков загрузили` : "Видео скачивается заранее и запустится автоматически"}</p>
              {role === "host" ? <button className={homeStyles.secondary} onClick={() => send("host_start_question")}>Запустить сейчас</button> : null}
            </div>
          ) : null}
          {state === "QUESTION" && playbackBlocked ? (
            <div className={styles.overlay}>
              <h2>Браузер остановил автовоспроизведение</h2>
              <p>Нажми кнопку — видео продолжится с актуального момента</p>
              <button className={homeStyles.primary} onClick={() => void resumePlayback()}>Запустить видео</button>
            </div>
          ) : null}
          {state === "REVEAL" && reveal ? (
            <div className={styles.revealBanner}>
              <span>Мем прислал</span>
              <div className={styles.revealNameCol} data-correct={role === "player" ? reveal.is_correct : undefined}>
                <div className={styles.revealNameRow}>
                  <strong>{reveal.correct_author.display_name}</strong>
                  {role === "player" && reveal.is_correct ? (
                    <span className={styles.scoreGain} aria-hidden="true">
                      <span className={styles.scoreGainInner}>
                        <span className={styles.scoreSlot}>
                          <span className={styles.scoreDigit}>+</span>
                        </span>
                        <span className={`${styles.scoreSlot} ${styles.scoreSlotSecond}`}>
                          <span className={styles.scoreDigit}>1</span>
                        </span>
                      </span>
                      <span className={`${styles.spark} ${styles.sparkA}`} />
                      <span className={`${styles.spark} ${styles.sparkB}`} />
                    </span>
                  ) : null}
                </div>
                {role === "player" ? (
                  <em data-correct={reveal.is_correct}>{reveal.is_correct ? "Верно!" : selected ? "Неверно" : "Нет ответа"}</em>
                ) : (
                  <em>Угадали: {reveal.correct_count}</em>
                )}
                {role === "player" && reveal.is_correct ? <span className={styles.verdictBar} aria-hidden="true" /> : null}
              </div>
            </div>
          ) : null}
          {videoError ? <div className={styles.videoError}>Видео не загрузилось. Проверьте сеть и обновите страницу.</div> : null}
        </div>
      </section>

      {/* One fixed-height slot for whichever action row is current (player's
          answer grid, host's reveal-question controls, or the post-reveal
          reactions) — these differ in natural height, and this used to be
          three separately-sized sections stacked straight into the grid, so
          switching between them (e.g. answering → REVEAL's reactions) grew
          or shrank this row and made the flexible stage above visibly jump
          to compensate. Centering a variable-height child inside a shared
          min-height keeps that row's box constant across every state. */}
      <div className={styles.actionsSlot}>
        {state === "QUESTION" && role === "player" ? (
          <>
            <section className={styles.answers} aria-label="Варианты ответа">
              {authors.map((author, index) => (
                <button
                  key={author.id}
                  type="button"
                  className={styles.answerButton}
                  data-selected={selected === author.id}
                  onClick={() => {
                    if (selected === author.id) return;
                    setSelected(author.id);
                    setAccepted(false);
                    send("answer_submit", { author_id: author.id });
                  }}
                >
                  <b className={styles.answerNumber}>{String(index + 1).padStart(2, "0")}</b>
                  <span className={styles.answerName}>{author.display_name}</span>
                </button>
              ))}
            </section>
            {/* Reserved space, not conditionally mounted in the grid above —
                the caption appearing/disappearing must never resize .answers
                itself or shift the buttons. */}
            <div className={styles.acceptedSlot}>
              {accepted ? <span className={styles.accepted}>Ответ принят</span> : null}
            </div>
          </>
        ) : null}
        {state === "QUESTION" && role === "host" ? (
          <section className={styles.hostControls}>
            <button className={homeStyles.secondary} disabled={countdown !== 0} onClick={() => send("host_reveal_question")}>Раскрыть ответ</button>
            <button className={styles.lobbyDanger} onClick={() => send("host_finish_game")}>Завершить игру</button>
          </section>
        ) : null}
        {state === "REVEAL" ? (
          <section className={styles.reactions}>
            {role === "player" ? (
              <>
                <button
                  type="button"
                  className={styles.reactionButton}
                  onClick={() => { if (videoRef.current) { videoRef.current.currentTime = 0; void videoRef.current.play(); } }}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                    <path d="M1 4v6h6M3.51 15a9 9 0 1 0 2.13-9.36L1 10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  <span>Повторить мем</span>
                </button>
                <button type="button" className={styles.reactionButton} data-active={reaction === 1} onClick={() => send("reaction_set", { value: 1 })}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                    <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  <span>Лайк</span>
                </button>
                <button type="button" className={styles.reactionButton} data-active={reaction === -1} onClick={() => send("reaction_set", { value: -1 })}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                    <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  <span>Дизлайк</span>
                </button>
                <button type="button" className={styles.reactionButton} data-active={reaction === null} onClick={() => send("reaction_set", { value: null })}>
                  <span>Пропустить</span>
                </button>
                <p className={styles.autoNext}>{question?.position === snapshot.pack.question_count ? `Итоги через ${revealCountdown ?? "—"} с` : `Следующий мем через ${revealCountdown ?? "—"} с`}</p>
              </>
            ) : (
              <>
                <button className={homeStyles.primary} onClick={() => send("host_next_question")}>Следующий вопрос →</button>
                <button className={styles.lobbyDanger} onClick={() => send("host_finish_game")}>Завершить игру</button>
              </>
            )}
          </section>
        ) : null}
      </div>
      {status !== "connected" ? <div className={styles.network}>Связь потеряна. Восстанавливаем…</div> : null}
      {error.text ? (
        <div
          role="alert"
          className={
            error.leaving
              ? `${homeStyles.toast} ${homeStyles.toastError} ${homeStyles.toastLeaving}`
              : `${homeStyles.toast} ${homeStyles.toastError}`
          }
          onClick={() => error.dismiss()}
        >
          {error.text}
        </div>
      ) : null}
      </div>
    </main>
    </PageTransition>
  );
}

export function GamePage({ role }: { role: "host" | "player" }) {
  const code = (useParams().code ?? "").toUpperCase();
  const [token, setToken] = useState(() => sessionStorage.getItem(tokenKey(role, code)));
  return (
    <PageTransition transitionKey={token ? "connected" : "invite"}>
      {!token && role === "player" ? (
        <InviteJoin code={code} onJoined={setToken} />
      ) : !token ? (
        <main className={styles.center}><h1>Нет доступа к комнате</h1><p>Откройте приглашение игрока и войдите под своим именем.</p><Link className={styles.linkButton} to={`/room/${code}`}>Войти в комнату</Link></main>
      ) : (
        <Connection code={code} role={role} token={token} />
      )}
    </PageTransition>
  );
}
