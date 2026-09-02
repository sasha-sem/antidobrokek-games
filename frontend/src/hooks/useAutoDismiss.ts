import { useCallback, useEffect, useRef, useState } from "react";

/** How long a toast stays up before dismissing itself, and how long its
    own exit takes — shared constants so every toast in the app behaves
    the same, the same reasoning as HOLD_CONFIRM_MS. */
export const TOAST_DISPLAY_MS = 4000;
export const TOAST_EXIT_MS = 400;

/**
 * A self-dismissing toast's text. `show(text)` displays it and starts the
 * auto-dismiss clock; `dismiss()` starts that same graceful exit early
 * (e.g. a click); `clear()` removes it immediately with no animation, for
 * wiping stale text at the start of an unrelated action rather than
 * "the user dismissed a notification."
 *
 * `dismiss()` reads the current text from a ref rather than the `text`
 * state — it's often called from a timeout closure captured back when
 * that timer was scheduled, where `text` would be whatever it was at
 * that render (stale), not necessarily current.
 */
export function useAutoDismiss(displayMs: number = TOAST_DISPLAY_MS, exitMs: number = TOAST_EXIT_MS) {
  const [text, setText] = useState("");
  const [leaving, setLeaving] = useState(false);
  const textRef = useRef("");
  const displayTimer = useRef<number | null>(null);
  const exitTimer = useRef<number | null>(null);

  const clearTimers = () => {
    if (displayTimer.current !== null) {
      window.clearTimeout(displayTimer.current);
      displayTimer.current = null;
    }
    if (exitTimer.current !== null) {
      window.clearTimeout(exitTimer.current);
      exitTimer.current = null;
    }
  };

  useEffect(() => clearTimers, []);

  const dismiss = useCallback(() => {
    if (!textRef.current || exitTimer.current !== null) return;
    setLeaving(true);
    exitTimer.current = window.setTimeout(() => {
      textRef.current = "";
      setText("");
      setLeaving(false);
      exitTimer.current = null;
    }, exitMs);
  }, [exitMs]);

  const show = useCallback(
    (value: string) => {
      clearTimers();
      textRef.current = value;
      setText(value);
      setLeaving(false);
      displayTimer.current = window.setTimeout(() => {
        displayTimer.current = null;
        dismiss();
      }, displayMs);
    },
    [displayMs, dismiss],
  );

  const clear = useCallback(() => {
    clearTimers();
    textRef.current = "";
    setText("");
    setLeaving(false);
  }, []);

  return { text, leaving, show, dismiss, clear };
}
