import { useCallback, useEffect, useRef, useState } from "react";

const STORAGE_KEY = "dobrokek.bgPlaying";

function readPersistedPlaying(): boolean {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw === null ? true : raw === "1";
  } catch {
    return true;
  }
}

function writePersistedPlaying(value: boolean) {
  try {
    localStorage.setItem(STORAGE_KEY, value ? "1" : "0");
  } catch {
    // Best-effort only (e.g. private browsing can block storage) — the
    // preference just won't survive a reload, playback itself is unaffected.
  }
}

interface Options {
  /** Home/Invite/Lobby (the default): the play/pause preference is shared
   *  and survives a reload via localStorage. GamePage passes `false` — that
   *  screen always arrives paused regardless of the stored preference, and
   *  toggling it there is local to that visit only, never written back. */
  persist?: boolean;
}

// A callback ref, not a plain useRef object: on GamePage the <video> this
// attaches to only mounts inside one of several conditional branches
// (never on the first render, which shows a loading/lobby state instead).
// A plain ref + a `useEffect(..., [])` would run its setup once, find
// videoRef.current still null at that point, bail, and never retry once
// the element actually appears later — the video would then only ever
// play via its own autoplay/loop HTML attributes, with none of this
// hook's stall/pause recovery wired up (looks "frozen" after the first
// hiccup). Tracking the node in state instead re-runs setup whenever the
// node itself changes, mount timing be damned.
export function useLoopingBackgroundVideo(options?: Options) {
  const persist = options?.persist ?? true;
  const [video, setVideo] = useState<HTMLVideoElement | null>(null);
  const userPaused = useRef(false);
  const [playing, setPlaying] = useState(true);
  const videoRef = useCallback((node: HTMLVideoElement | null) => setVideo(node), []);

  useEffect(() => {
    if (!video) return;
    video.muted = true;
    video.loop = true;

    const kick = () => {
      if (userPaused.current) return;
      if (video.ended || video.currentTime >= video.duration - 0.05) {
        video.currentTime = 0;
      }
      if (video.paused) void video.play()?.catch(() => {});
    };
    const onVisibility = () => {
      if (!document.hidden) kick();
    };

    const shouldStartPaused = persist ? !readPersistedPlaying() : true;
    userPaused.current = shouldStartPaused;
    setPlaying(!shouldStartPaused);
    if (shouldStartPaused) {
      video.pause();
    } else {
      void video.play()?.catch(() => {});
    }

    video.addEventListener("ended", kick);
    video.addEventListener("pause", kick);
    video.addEventListener("stalled", kick);
    video.addEventListener("suspend", kick);
    video.addEventListener("error", kick);
    document.addEventListener("visibilitychange", onVisibility);
    const watchdog = window.setInterval(kick, 1500);

    return () => {
      video.removeEventListener("ended", kick);
      video.removeEventListener("pause", kick);
      video.removeEventListener("stalled", kick);
      video.removeEventListener("suspend", kick);
      video.removeEventListener("error", kick);
      document.removeEventListener("visibilitychange", onVisibility);
      window.clearInterval(watchdog);
    };
  }, [video, persist]);

  const toggle = useCallback(() => {
    if (!video) return;
    if (userPaused.current) {
      userPaused.current = false;
      void video.play()?.catch(() => {});
      setPlaying(true);
      if (persist) writePersistedPlaying(true);
    } else {
      userPaused.current = true;
      video.pause();
      setPlaying(false);
      if (persist) writePersistedPlaying(false);
    }
  }, [video, persist]);

  return { videoRef, playing, toggle };
}
