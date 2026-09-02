import { useCallback, useRef, useState } from "react";

/** Standard hold duration for hold-to-confirm actions across the app —
    kept as one shared value rather than each caller picking its own, so
    every "hold to confirm" gesture feels the same regardless of what it
    confirms. */
export const HOLD_CONFIRM_MS = 1000;

/**
 * Press-and-hold confirmation for actions that are consequential and hard
 * to undo through the UI (closing a room, marking yourself ready when
 * there's no "unready" control). Replaces a native window.confirm() with
 * a tactile press-and-hold: releasing early cancels, holding for `holdMs`
 * fires `onConfirm`.
 */
export function useHoldToConfirm(onConfirm: () => void, holdMs: number = HOLD_CONFIRM_MS) {
  const [holding, setHolding] = useState(false);
  const timer = useRef<number | null>(null);

  const cancel = useCallback(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
    setHolding(false);
  }, []);

  const start = useCallback(() => {
    if (timer.current !== null) return;
    setHolding(true);
    timer.current = window.setTimeout(() => {
      timer.current = null;
      setHolding(false);
      onConfirm();
    }, holdMs);
  }, [holdMs, onConfirm]);

  return { holding, start, cancel };
}
