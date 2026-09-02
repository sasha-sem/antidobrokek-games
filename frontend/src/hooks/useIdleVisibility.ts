import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Standard "player controls fade during idle playback" pattern: visible
 * immediately on any activity, hidden again after `delayMs` of none.
 * `wake()` is meant to be wired to pointer/keyboard activity on whatever
 * container counts as "the player" (see .stage's onPointerMove/onPointerDown
 * in GamePage.tsx). While `active` is false the controls just stay shown —
 * nothing to hide from (no video playing, or nothing worth idling away).
 */
export function useIdleVisibility(active: boolean, delayMs = 2500) {
  const [visible, setVisible] = useState(true);
  const hideTimer = useRef<number | null>(null);

  const clearTimer = () => {
    if (hideTimer.current !== null) {
      window.clearTimeout(hideTimer.current);
      hideTimer.current = null;
    }
  };

  const wake = useCallback(() => {
    setVisible(true);
    clearTimer();
    if (active) {
      hideTimer.current = window.setTimeout(() => {
        setVisible(false);
        hideTimer.current = null;
      }, delayMs);
    }
  }, [active, delayMs]);

  useEffect(() => {
    wake();
    return clearTimer;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  useEffect(() => clearTimer, []);

  return { visible, wake };
}
