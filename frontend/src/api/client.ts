import type { ApiErrorPayload, RoomSnapshot } from "../types/events";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code = "api_error",
  ) {
    super(message);
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.ok) return (await response.json()) as T;
  let payload: ApiErrorPayload = {};
  try {
    payload = (await response.json()) as ApiErrorPayload;
  } catch {
    // The reverse proxy can reject a body before FastAPI sees it.
  }
  const validation = Array.isArray(payload.detail) ? payload.detail[0]?.msg : payload.detail;
  throw new ApiError(
    payload.error?.message ?? validation ?? "Сервер не смог обработать запрос",
    response.status,
    payload.error?.code,
  );
}

export async function joinRoom(code: string, displayName: string, identityId: string) {
  const response = await fetch(`/api/rooms/${encodeURIComponent(code)}/join`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_name: displayName, identity_id: identityId }),
  });
  return parseResponse<{ player_id: string; reconnect_token: string }>(response);
}

export function createRoom(
  hostSecret: string,
  pack: File,
  graceSeconds: number,
  onProgress: (progress: number) => void,
): Promise<{ room_code: string; host_token: string; host_url: string; player_url: string }> {
  return new Promise((resolve, reject) => {
    const body = new FormData();
    body.append("host_secret", hostSecret);
    body.append("pack", pack);
    body.append("question_grace_seconds", String(graceSeconds));
    const request = new XMLHttpRequest();
    request.open("POST", "/api/host/rooms");
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    request.onerror = () => reject(new ApiError("Загрузка прервана", 0, "upload_interrupted"));
    request.onload = () => {
      let payload: Record<string, unknown> = {};
      try {
        payload = JSON.parse(request.responseText) as Record<string, unknown>;
      } catch {
        // Keep the fallback message below.
      }
      if (request.status >= 200 && request.status < 300) {
        resolve(payload as { room_code: string; host_token: string; host_url: string; player_url: string });
      } else {
        const error = payload.error as { code?: string; message?: string } | undefined;
        reject(new ApiError(error?.message ?? "Не удалось загрузить пак", request.status, error?.code));
      }
    };
    request.send(body);
  });
}

export async function closeCurrentRoom(hostSecret: string): Promise<void> {
  const body = new FormData();
  body.append("host_secret", hostSecret);
  const response = await fetch("/api/host/rooms/current/close", {
    method: "POST",
    body,
  });
  if (response.ok) return;
  await parseResponse(response);
}

export async function getPublicSnapshot(code: string): Promise<RoomSnapshot> {
  return parseResponse(await fetch(`/api/rooms/${encodeURIComponent(code)}/snapshot`));
}
