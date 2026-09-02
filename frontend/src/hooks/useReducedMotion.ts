import { useState } from "react";

export function useReducedMotion(): boolean {
  const [reduced] = useState(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  return reduced;
}
