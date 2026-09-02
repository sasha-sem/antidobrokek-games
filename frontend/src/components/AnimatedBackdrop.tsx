import { ReactNode } from "react";
import { useLoopingBackgroundVideo } from "../hooks/useLoopingBackgroundVideo";
import styles from "./AnimatedBackdrop.module.css";

interface AnimatedBackdropProps {
  /** Rendered inside the floatUp-animated centered column. */
  children: ReactNode;
  /** Rendered as direct children of <main>, outside the animated column —
      for fixed-position overlays (toasts) that must stay viewport-fixed even
      while the column's entrance transform is running. */
  overlays?: ReactNode;
}

export function AnimatedBackdrop({ children, overlays }: AnimatedBackdropProps) {
  const { videoRef, playing, toggle } = useLoopingBackgroundVideo();

  return (
    <main className={styles.page}>
      <video
        ref={videoRef}
        className={styles.bgVideo}
        autoPlay
        muted
        loop
        playsInline
        preload="auto"
        src="/bg.mp4"
      />
      <div className={styles.bgOverlayVignette} />
      <div className={styles.bgOverlayDim} />

      <button
        type="button"
        className={styles.pauseButton}
        data-playing={playing}
        onClick={toggle}
        aria-label={playing ? "Остановить фон" : "Запустить фон"}
      >
        <span className={styles.pauseIcon} aria-hidden="true">
          <svg className={styles.pauseIconGlyph} data-variant="pause" width="8.5" height="10.2" viewBox="0 0 10 12" fill="currentColor">
            <rect x="0" width="3" height="12" rx="1" />
            <rect x="7" width="3" height="12" rx="1" />
          </svg>
          <svg className={styles.pauseIconGlyph} data-variant="play" width="8.5" height="10.2" viewBox="0 0 10 12" fill="currentColor">
            <polygon points="0,0 10,6 0,12" />
          </svg>
        </span>
        <span className={styles.pauseLabel} aria-hidden="true">{playing ? "стоп" : "пуск"}</span>
      </button>

      <div className={styles.content}>
        <div className={styles.inner}>{children}</div>
      </div>

      {overlays}
    </main>
  );
}
