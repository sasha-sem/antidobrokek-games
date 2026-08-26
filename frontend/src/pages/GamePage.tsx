import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Scoreboard } from "../components/Scoreboard";
import { useRoomSocket } from "../hooks/useRoomSocket";
import { useSynchronizedPlayback } from "../hooks/useSynchronizedPlayback";
import type { Author, CurrentQuestion, RoomSnapshot, ScoreRow, ServerEnvelope } from "../types/events";
import { tokenKey } from "../utils/identity";
import { InviteJoin } from "./InvitePage";
import styles from "./GamePage.module.css";

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
  const [soundUnlocked, setSoundUnlocked] = useState(role === "host");
  const [error, setError] = useState("");
  const [videoError, setVideoError] = useState(false);
  const [copied, setCopied] = useState(false);
  const [ownPlayerId, setOwnPlayerId] = useState<string | null>(null);
  const [muted, setMuted] = useState(false);
  const [volume, setVolume] = useState(1);
  const [now, setNow] = useState(Date.now());
  const videoRef = useRef<HTMLVideoElement>(null);
  const readyQuestion = useRef("");

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
      setError("Ведущий удалил вас из комнаты");
    } else if (event.type === "room_state_changed" && payload.state === "CLOSED") {
      setError("Ведущий закрыл комнату");
    } else if (event.type === "error") {
      setError(String(payload.message ?? "Ошибка игрового сервера"));
    }
  }, [selected]);

  const { status, serverOffsetMs, send } = useRoomSocket(code, role, token, onEvent);
  const question = snapshot?.current_question;
  const state = snapshot?.room.state;

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 200);
    return () => window.clearInterval(timer);
  }, []);

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

  const mediaLoaded = () => {
    if (state !== "PRELOADING" || !question) return;
    const key = `${question.position}:${question.media_url}`;
    if (readyQuestion.current === key) return;
    readyQuestion.current = key;
    if (role === "player") send("player_media_ready");
  };

  const unlockSound = async () => {
    try {
      const AudioContextClass = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      if (AudioContextClass) {
        const context = new AudioContextClass();
        await context.resume();
        const oscillator = context.createOscillator();
        const gain = context.createGain();
        gain.gain.value = 0;
        oscillator.connect(gain);
        gain.connect(context.destination);
        oscillator.start();
        oscillator.stop(context.currentTime + 0.01);
      }
      setSoundUnlocked(true);
    } catch {
      setError("Не удалось подготовить звук");
    }
  };

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
    return <main className={styles.center}><div className={styles.loader} /><h1>Подключаемся…</h1><p>{status === "reconnecting" ? "Сеть прервалась, пытаемся снова" : `Комната ${code}`}</p>{error ? <p className={styles.error}>{error}</p> : null}</main>;
  }

  const connectedCount = snapshot.players.filter((item) => item.is_connected).length;
  const ownPlayer = snapshot.players.find((item) => item.id === ownPlayerId);

  if (state === "FINISHED") {
    const winners = snapshot.scoreboard.filter((row) => row.rank === 1);
    return (
      <main className={styles.final}>
        <p className={styles.kicker}>Игра окончена</p>
        <h1>{winners.length > 1 ? "Ничья!" : "Победитель"}</h1>
        <div className={styles.winner}>{winners.map((winner) => winner.display_name).join(" + ")}</div>
        <Scoreboard rows={snapshot.scoreboard} total={snapshot.pack.question_count} />
        {snapshot.popular_meme ? <p>Самый популярный мем: рейтинг {snapshot.popular_meme.rating}, голосов {snapshot.popular_meme.votes}</p> : <p>Мемы в этой игре не оценивали</p>}
        {role === "host" ? <button className={styles.danger} onClick={() => send("host_close_room")}>Закрыть комнату</button> : null}
        <Link className={styles.linkButton} to="/">На главную</Link>
      </main>
    );
  }

  if (state === "LOBBY") {
    return (
      <main className={styles.lobby}>
        <header><Link to="/" className={styles.logo}>Доброкек<span>.</span></Link><div className={styles.connection} data-status={status}>{status === "connected" ? "В сети" : "Переподключение…"}</div></header>
        <section className={styles.lobbyHero}>
          <p>{snapshot.pack.title}</p>
          <h1>{code}</h1>
          <button className={styles.copy} onClick={copyInvite}>{copied ? "Ссылка скопирована ✓" : "Скопировать приглашение"}</button>
          <span>{snapshot.pack.question_count} вопросов · {snapshot.players.length}/5 игроков</span>
        </section>
        <section className={styles.playerGrid}>
          {snapshot.players.map((item, index) => <article key={item.id}><b>{String(index + 1).padStart(2, "0")}</b><h2>{item.display_name}</h2><span>{item.is_connected ? (item.is_ready ? "Готов" : "Не готов") : "Не в сети"}</span>{role === "host" ? <button onClick={() => send("host_kick_player", { player_id: item.id })} aria-label={`Удалить ${item.display_name}`}>×</button> : null}</article>)}
          {Array.from({ length: Math.max(0, 5 - snapshot.players.length) }, (_, index) => <article key={`empty-${index}`} className={styles.emptySlot}><b>{String(snapshot.players.length + index + 1).padStart(2, "0")}</b><span>Свободно</span></article>)}
        </section>
        <section className={styles.lobbyAction}>
          {role === "player" ? <>
            {!soundUnlocked ? <button className={styles.primary} onClick={unlockSound}>🔊 Включить звук и подготовиться</button> : <button className={styles.primary} disabled={ownPlayer?.is_ready} onClick={() => send("player_ready", { ready: true })}>{ownPlayer?.is_ready ? "Готово — ждём остальных" : "Готов"}</button>}
            <p>{ownPlayer?.is_ready ? "Игра начнётся автоматически, когда все подключённые игроки будут готовы" : "Сначала включи звук, затем нажми «Готов» после того, как друзья войдут"}</p>
          </> : <>
            <button className={styles.primary} disabled={!snapshot.players.length || snapshot.players.some((item) => item.is_connected && !item.is_ready)} onClick={() => send("host_start_game")}>Начать игру</button>
            <button className={styles.danger} onClick={() => send("host_close_room")}>Закрыть</button>
          </>}
        </section>
        {error ? <div role="alert" className={styles.toast}>{error}</div> : null}
      </main>
    );
  }

  return (
    <main className={styles.game}>
      <header className={styles.gameHeader}>
        <span className={styles.logo}>Доброкек<span>.</span></span>
        <strong>Вопрос {question?.position ?? "—"}/{snapshot.pack.question_count}</strong>
        <div className={styles.timer} data-low={countdown !== null && countdown <= 3}>{state === "PRELOADING" ? "Загрузка" : state === "REVEAL" ? "Ответ" : `${countdown ?? "—"} с`}</div>
        <span>Комната {code}</span>
      </header>
      <section className={styles.gameGrid}>
        <div className={styles.stage}>
          {question ? <video ref={videoRef} src={question.media_url} playsInline preload="auto" controls={state === "REVEAL"} muted={muted} onCanPlay={mediaLoaded} onError={() => setVideoError(true)} onContextMenu={(event) => event.preventDefault()} /> : null}
          {question ? <div className={styles.soundControls}><button aria-label={muted ? "Включить звук" : "Выключить звук"} onClick={() => { const next = !muted; if (videoRef.current) videoRef.current.muted = next; setMuted(next); if (!next) { clearAutoplayMuted(); void videoRef.current?.play(); } }}>{muted ? "🔇" : "🔊"}</button><input aria-label="Громкость" type="range" min="0" max="1" step="0.05" value={volume} onChange={(event) => { const next = Number(event.target.value); setVolume(next); if (videoRef.current) videoRef.current.volume = next; }} />{autoplayMuted ? <span>Нажми 🔇, чтобы включить звук</span> : null}</div> : null}
          {state === "PRELOADING" ? <div className={styles.overlay}><div className={styles.loader} /><h2>Готовим мем</h2><p>{role === "host" ? `${mediaReady.size}/${connectedCount} игроков загрузили` : "Видео скачивается заранее и запустится автоматически"}</p>{role === "host" ? <button className={styles.secondary} onClick={() => send("host_start_question")}>Запустить сейчас</button> : null}</div> : null}
          {state === "QUESTION" && playbackBlocked ? <div className={styles.overlay}><h2>Браузер остановил автовоспроизведение</h2><p>Нажми кнопку — видео продолжится с актуального момента</p><button className={styles.primary} onClick={() => void resumePlayback()}>▶ Запустить видео</button></div> : null}
          {state === "REVEAL" && reveal ? <div className={styles.revealBanner}><span>Мем прислал</span><strong>{reveal.correct_author.display_name}</strong>{role === "player" ? <em data-correct={reveal.is_correct}>{reveal.is_correct ? "Верно! +1" : selected ? "Неверно" : "Нет ответа"}</em> : <em>Угадали: {reveal.correct_count}</em>}</div> : null}
          {videoError ? <div className={styles.videoError}>Видео не загрузилось. Проверьте сеть и обновите страницу.</div> : null}
        </div>
      </section>

      {state === "QUESTION" && role === "player" ? <section className={styles.answers} aria-label="Варианты ответа">{authors.map((author, index) => <button key={author.id} className={selected === author.id ? styles.selected : undefined} onClick={() => { setSelected(author.id); setAccepted(false); send("answer_submit", { author_id: author.id }); }}><kbd>{index + 1}</kbd>{author.display_name}</button>)}{accepted ? <span className={styles.accepted}>✓ Ответ принят</span> : null}</section> : null}
      {state === "QUESTION" && role === "host" ? <section className={styles.hostControls}><button className={styles.secondary} disabled={countdown !== 0} onClick={() => send("host_reveal_question")}>Раскрыть ответ</button><button className={styles.danger} onClick={() => send("host_finish_game")}>Завершить игру</button></section> : null}
      {state === "REVEAL" ? <section className={styles.reactions}>{role === "player" ? <><button onClick={() => { if (videoRef.current) { videoRef.current.currentTime = 0; void videoRef.current.play(); } }}>↻ <span>Повторить мем</span></button><button data-active={reaction === 1} onClick={() => send("reaction_set", { value: 1 })}>👍 <span>Лайк</span></button><button data-active={reaction === -1} onClick={() => send("reaction_set", { value: -1 })}>👎 <span>Дизлайк</span></button><button data-active={reaction === null} onClick={() => send("reaction_set", { value: null })}><span>Пропустить</span></button><p className={styles.autoNext}>{question?.position === snapshot.pack.question_count ? `Итоги через ${revealCountdown ?? "—"} с` : `Следующий мем через ${revealCountdown ?? "—"} с`}</p></> : <><button className={styles.primary} onClick={() => send("host_next_question")}>Следующий вопрос →</button><button className={styles.danger} onClick={() => send("host_finish_game")}>Завершить игру</button></>}</section> : null}
      {status !== "connected" ? <div className={styles.network}>Связь потеряна. Восстанавливаем…</div> : null}
      {error ? <div role="alert" className={styles.toast} onClick={() => setError("")}>{error}</div> : null}
    </main>
  );
}

export function GamePage({ role }: { role: "host" | "player" }) {
  const code = (useParams().code ?? "").toUpperCase();
  const [token, setToken] = useState(() => sessionStorage.getItem(tokenKey(role, code)));
  if (!token && role === "player") return <InviteJoin code={code} onJoined={setToken} />;
  if (!token) return <main className={styles.center}><h1>Нет доступа к комнате</h1><p>Откройте приглашение игрока и войдите под своим именем.</p><Link className={styles.linkButton} to={`/room/${code}`}>Войти в комнату</Link></main>;
  return <Connection code={code} role={role} token={token} />;
}
