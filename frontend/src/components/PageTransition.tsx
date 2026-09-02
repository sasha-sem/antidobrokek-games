import { useEffect, useRef, useState, type ReactNode } from "react";
import styles from "./PageTransition.module.css";

// Keep in sync with .paneExiting's animation-duration in PageTransition.module.css.
const EXIT_MS = 220;

/**
 * Wraps whatever screen is current in a fade+drift handoff whenever
 * `transitionKey` changes — the outgoing screen plays its exit and stays
 * mounted until that finishes, then the incoming one mounts fresh (a new
 * DOM node, via `key={displayKey}`, so its own entrance always restarts
 * cleanly rather than fighting leftover animation state).
 *
 * While `transitionKey` stays the same, `children` is kept live in sync
 * on every render with no transition at all — this only fires on an
 * actual screen change, never on ordinary content updates within one
 * screen (e.g. live game state ticking).
 *
 * The swap is timer-backed, not purely `animationend`-driven: a
 * backgrounded tab (or any other reason the animation never actually
 * fires its end event) would otherwise leave the OLD screen stuck on
 * display forever — for a boundary like "you just joined the room", that
 * would mean the player never reaches the lobby at all, not just a
 * missed flourish. Whichever fires first wins; the other is a no-op.
 */
export function PageTransition({ transitionKey, children }: { transitionKey: string; children: ReactNode }) {
  const [displayKey, setDisplayKey] = useState(transitionKey);
  const [displayChildren, setDisplayChildren] = useState<ReactNode>(children);
  const [exiting, setExiting] = useState(false);
  const childrenRef = useRef(children);
  childrenRef.current = children;

  useEffect(() => {
    if (transitionKey === displayKey) {
      setDisplayChildren(children);
      return;
    }
    setExiting(true);
  }, [transitionKey, displayKey, children]);

  useEffect(() => {
    if (!exiting) return;
    const safety = window.setTimeout(() => {
      setDisplayKey(transitionKey);
      setDisplayChildren(childrenRef.current);
      setExiting(false);
    }, EXIT_MS + 300);
    return () => window.clearTimeout(safety);
  }, [exiting, transitionKey]);

  return (
    // .viewport itself is never transformed and sized purely by normal
    // flow, so its own box always matches the screen's real height. .pane
    // is what actually moves (translateY ±10px) — on a min-height:100vh
    // screen that briefly pushes the painted box past the viewport edge,
    // which triggers a real (if momentary) page scrollbar despite nothing
    // about the layout actually changing. Clipping at .viewport contains
    // that transform overflow without capping legitimate taller content,
    // since .viewport's own computed height already accounts for it.
    <div className={styles.viewport}>
      <div
        key={displayKey}
        className={exiting ? `${styles.pane} ${styles.paneExiting}` : styles.pane}
        onAnimationEnd={(event) => {
          if (event.target !== event.currentTarget || !exiting) return;
          setDisplayKey(transitionKey);
          setDisplayChildren(childrenRef.current);
          setExiting(false);
        }}
      >
        {displayChildren}
      </div>
    </div>
  );
}
