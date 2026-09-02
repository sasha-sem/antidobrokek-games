import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { AnimatedBackdrop } from "../components/AnimatedBackdrop";
import { Scoreboard } from "../components/Scoreboard";
import { useReducedMotion } from "../hooks/useReducedMotion";
import type { RoomSnapshot } from "../types/events";
import { pluralizeRu } from "../utils/plural";
import faceSrc from "../assets/face512x512.png";
import homeStyles from "./HomePage.module.css";
import styles from "./FinishedScreen.module.css";

// Must match .introSmiley's animation-duration in FinishedScreen.module.css
// — this is the safety fallback if `animationend` never fires (e.g. the
// tab was backgrounded and the browser throttled the animation).
const INTRO_MS = 3000;

interface ConfettiBit {
  x: number; y: number; vx: number; vy: number;
  w: number; h: number; rot: number; vr: number; c: string;
}

function fireConfetti(canvas: HTMLCanvasElement): () => void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return () => {};
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = window.innerWidth * dpr;
  canvas.height = window.innerHeight * dpr;
  ctx.scale(dpr, dpr);

  const colors = ["#e6fd46", "#b9c98a", "#f2f2f2", "#8fa83a", "#eeff9e"];
  const bits: ConfettiBit[] = [];
  const spawn = (n: number, x: number, y: number, power: number) => {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2;
      const s = Math.random() * power + power * 0.25;
      bits.push({
        x, y,
        vx: Math.cos(a) * s,
        vy: Math.sin(a) * s - power * 0.5,
        w: 5 + Math.random() * 9,
        h: 8 + Math.random() * 14,
        rot: Math.random() * 6.3,
        vr: (Math.random() - 0.5) * 0.35,
        c: colors[(Math.random() * colors.length) | 0],
      });
    }
  };
  spawn(150, window.innerWidth * 0.5, window.innerHeight * 0.42, 13);
  spawn(90, window.innerWidth * 0.08, window.innerHeight * 0.75, 15);
  spawn(90, window.innerWidth * 0.92, window.innerHeight * 0.75, 15);

  let frameId = 0;
  const loop = () => {
    ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
    for (let i = bits.length - 1; i >= 0; i--) {
      const b = bits[i];
      b.vy += 0.22;
      b.x += b.vx;
      b.y += b.vy;
      b.rot += b.vr;
      if (b.y > window.innerHeight + 40) {
        bits.splice(i, 1);
        continue;
      }
      ctx.save();
      ctx.translate(b.x, b.y);
      ctx.rotate(b.rot);
      ctx.fillStyle = b.c;
      ctx.fillRect(-b.w / 2, -b.h / 2, b.w, b.h * Math.abs(Math.cos(b.rot)));
      ctx.restore();
    }
    if (bits.length) frameId = requestAnimationFrame(loop);
  };
  frameId = requestAnimationFrame(loop);
  return () => cancelAnimationFrame(frameId);
}

export function FinishedScreen({
  snapshot,
  role,
  onCloseRoom,
}: {
  snapshot: RoomSnapshot;
  role: "host" | "player";
  onCloseRoom: () => void;
}) {
  const reducedMotion = useReducedMotion();
  const [introDone, setIntroDone] = useState(reducedMotion);
  const smileyRef = useRef<HTMLImageElement>(null);
  const confettiRef = useRef<HTMLCanvasElement>(null);

  const winners = snapshot.scoreboard.filter((row) => row.rank === 1);
  const isTie = winners.length > 1;
  const winnerNames = winners.map((winner) => winner.display_name).join(" + ");
  const winnerScore = winners[0]?.score ?? 0;

  // Waits for the smiley's own animation to actually finish (more reliable
  // than a bare timer alone — a backgrounded tab can throttle CSS
  // animations) before revealing the results, with a timed fallback in
  // case animationend never fires at all.
  useEffect(() => {
    if (reducedMotion) return;
    const node = smileyRef.current;
    if (!node) return;
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      setIntroDone(true);
    };
    node.addEventListener("animationend", finish);
    const safety = window.setTimeout(finish, INTRO_MS + 300);
    return () => {
      node.removeEventListener("animationend", finish);
      window.clearTimeout(safety);
    };
  }, [reducedMotion]);

  useEffect(() => {
    if (!introDone || reducedMotion) return;
    const canvas = confettiRef.current;
    if (!canvas) return;
    let cancel = () => {};
    const timer = window.setTimeout(() => {
      cancel = fireConfetti(canvas);
    }, 400);
    return () => {
      window.clearTimeout(timer);
      cancel();
    };
  }, [introDone, reducedMotion]);

  return (
    <AnimatedBackdrop
      overlays={
        <>
          {!introDone ? (
            <div className={styles.intro} aria-hidden="true">
              <img ref={smileyRef} className={styles.introSmiley} src={faceSrc} alt="" />
              <div className={styles.introCaption}>Считаем результаты</div>
            </div>
          ) : null}
          {!reducedMotion ? <canvas ref={confettiRef} className={styles.confettiCanvas} aria-hidden="true" /> : null}
        </>
      }
    >
      {introDone ? (
        <div className={styles.finalContent}>
          <p className={styles.finalKicker}>Игра окончена</p>
          <h1 className={styles.finalTitle}>{isTie ? "Ничья!" : "Победитель"}</h1>
          <div className={styles.finalWinner}>
            <img className={styles.finalAvatar} src={faceSrc} alt="" aria-hidden="true" />
            <span>{winnerNames}</span>
          </div>
          <p className={styles.finalScore}>
            {winnerScore.toLocaleString("ru-RU")} {pluralizeRu(winnerScore, "очко", "очка", "очков")}
          </p>
          <Scoreboard rows={snapshot.scoreboard} total={snapshot.pack.question_count} baseDelayMs={1500} />
          <p className={styles.finalMeta}>
            {snapshot.popular_meme
              ? `Самый популярный мем: рейтинг ${snapshot.popular_meme.rating}, голосов ${snapshot.popular_meme.votes}`
              : "Мемы в этой игре не оценивали"}
          </p>
          <div className={styles.finalActions}>
            {role === "host" ? <button className={styles.finalDanger} onClick={onCloseRoom}>Закрыть комнату</button> : null}
            <Link className={`${homeStyles.secondary} ${styles.finalLink}`} to="/">На главную</Link>
          </div>
        </div>
      ) : null}
    </AnimatedBackdrop>
  );
}
