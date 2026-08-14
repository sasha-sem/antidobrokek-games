const KEY = "dobrokek.identity";

export function getIdentity(): string {
  const existing = localStorage.getItem(KEY);
  if (existing) return existing;
  const identity = crypto.randomUUID();
  localStorage.setItem(KEY, identity);
  return identity;
}

export function tokenKey(role: "host" | "player", code: string): string {
  return `dobrokek.${role}.${code.toUpperCase()}`;
}
