import { Dispatch, RefObject, SetStateAction, useCallback, useEffect, useRef, useState } from "react";
import type { CurrentQuestion } from "../types/events";

interface PlaybackOptions {
  active: boolean;
  question?: CurrentQuestion;
  serverOffsetMs: number;
  setMuted: Dispatch<SetStateAction<boolean>>;
  videoRef: RefObject<HTMLVideoElement | null>;
}

export function useSynchronizedPlayback({
  active,
  question,
  serverOffsetMs,
  setMuted,
  videoRef,
}: PlaybackOptions) {
  const [playbackBlocked, setPlaybackBlocked] = useState(false);
  const [autoplayMuted, setAutoplayMuted] = useState(false);
  const startedQuestion = useRef("");
  const questionKey = question?.starts_at ? `${question.position}:${question.starts_at}` : "";

  useEffect(() => {
    startedQuestion.current = "";
    setPlaybackBlocked(false);
    setAutoplayMuted(false);
  }, [questionKey]);

  const playAtServerTime = useCallback(async () => {
    const video = videoRef.current;
    if (!active || !video || !question?.starts_at || !question.ends_at) return false;
    const serverNow = Date.now() + serverOffsetMs;
    const startsAt = new Date(question.starts_at).getTime();
    const endsAt = new Date(question.ends_at).getTime();
    if (serverNow < startsAt || serverNow >= endsAt) return false;

    const expectedTime = Math.max(
      0,
      Math.min((serverNow - startsAt) / 1000, question.duration_ms / 1000),
    );
    if (Math.abs(video.currentTime - expectedTime) > 1.25) {
      video.currentTime = expectedTime;
    }
    if (startedQuestion.current === questionKey && !video.paused) return true;

    try {
      await video.play();
      startedQuestion.current = questionKey;
      setPlaybackBlocked(false);
      return true;
    } catch {
      // Muted autoplay is allowed even under strict browser policies. Keep the
      // video synchronized and let the player enable sound with one click.
      video.muted = true;
      setMuted(true);
      try {
        await video.play();
        startedQuestion.current = questionKey;
        setAutoplayMuted(true);
        setPlaybackBlocked(false);
        return true;
      } catch {
        setPlaybackBlocked(true);
        return false;
      }
    }
  }, [active, question?.duration_ms, question?.ends_at, question?.starts_at, questionKey, serverOffsetMs, setMuted, videoRef]);

  useEffect(() => {
    if (!active || !question?.starts_at || !question.ends_at) return;
    const delay = new Date(question.starts_at).getTime() - (Date.now() + serverOffsetMs);
    const timer = window.setTimeout(() => void playAtServerTime(), Math.max(0, delay));
    return () => window.clearTimeout(timer);
  }, [active, playAtServerTime, question?.ends_at, question?.starts_at, serverOffsetMs]);

  useEffect(() => {
    if (!active) return;
    const watchdog = window.setInterval(() => void playAtServerTime(), 750);
    const resumeVisible = () => {
      if (document.visibilityState === "visible") void playAtServerTime();
    };
    document.addEventListener("visibilitychange", resumeVisible);
    return () => {
      window.clearInterval(watchdog);
      document.removeEventListener("visibilitychange", resumeVisible);
    };
  }, [active, playAtServerTime]);

  return {
    autoplayMuted,
    clearAutoplayMuted: () => setAutoplayMuted(false),
    playbackBlocked,
    resumePlayback: playAtServerTime,
  };
}
