import { useCallback, useState } from "react";

/**
 * Drop-in replacement for a form's native "fill out this field" bubble.
 * Call `validate(formElement)` in a submit handler instead of trusting the
 * browser's own implicit check — it runs the same constraint validation
 * (required, minLength, …) but reports failures as field-name-keyed state
 * instead of an OS tooltip, so each field can render its own inline error
 * (see .field input[data-invalid] / .file[data-invalid] in
 * HomePage.module.css, shared by every form via that one CSS Modules
 * file). Requires each validated input to have a stable `name`. Clear a
 * single field's error as soon as the user touches it again via
 * `clear(name)`.
 */
export function useFieldErrors() {
  const [invalid, setInvalid] = useState<Record<string, boolean>>({});

  const validate = useCallback((form: HTMLFormElement): boolean => {
    const fields = Array.from(form.elements).filter(
      (el): el is HTMLInputElement => el instanceof HTMLInputElement && el.willValidate,
    );
    const bad = fields.filter((el) => !el.checkValidity());
    if (bad.length === 0) {
      setInvalid({});
      return true;
    }
    const names = bad.map((el) => el.name);
    // Toggle off, then back on — setting an already-"true" value is a
    // no-op React won't re-render for, so a field that's still empty on a
    // second submit wouldn't shake again without this. The off/on round
    // trip is what makes the CSS animation actually restart. setTimeout
    // rather than requestAnimationFrame: rAF callbacks are suspended
    // entirely on a backgrounded/hidden tab, which would leave the field
    // stuck "off" until the tab regains visibility.
    setInvalid((prev) => {
      const next = { ...prev };
      for (const name of names) next[name] = false;
      return next;
    });
    window.setTimeout(() => {
      setInvalid((prev) => {
        const next = { ...prev };
        for (const name of names) next[name] = true;
        return next;
      });
    }, 0);
    bad[0].focus();
    return false;
  }, []);

  const clear = useCallback((name: string) => {
    setInvalid((prev) => (prev[name] ? { ...prev, [name]: false } : prev));
  }, []);

  return { invalid, validate, clear };
}
