import { useCallback, useEffect, useRef, useState } from "react";

export function useLoopingBackgroundVideo() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const userPaused = useRef(false);
  const [playing, setPlaying] = useState(true);

  useEffect(() => {
    const video = videoRef.current;
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

    void video.play()?.catch(() => {});
    video.addEventListener("ended", kick);
    video.addEventListener("pause", kick);
    video.addEventListener("stalled", kick);
    video.addEventListener("suspend", kick);
    document.addEventListener("visibilitychange", onVisibility);
    const watchdog = window.setInterval(kick, 2000);

    return () => {
      video.removeEventListener("ended", kick);
      video.removeEventListener("pause", kick);
      video.removeEventListener("stalled", kick);
      video.removeEventListener("suspend", kick);
      document.removeEventListener("visibilitychange", onVisibility);
      window.clearInterval(watchdog);
    };
  }, []);

  const toggle = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      userPaused.current = false;
      void video.play()?.catch(() => {});
      setPlaying(true);
    } else {
      userPaused.current = true;
      video.pause();
      setPlaying(false);
    }
  }, []);

  return { videoRef, playing, toggle };
}
