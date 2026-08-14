export type RoomState =
  | "LOBBY"
  | "PRELOADING"
  | "QUESTION"
  | "REVEAL"
  | "FINISHED"
  | "CLOSED"
  | "CANCELLED";

export interface Author {
  id: string;
  display_name: string;
}

export interface Player {
  id: string;
  display_name: string;
  is_connected: boolean;
  is_ready: boolean;
}

export interface ScoreRow {
  rank: number;
  player_id: string;
  display_name: string;
  score: number;
  accuracy_percent?: number;
  evaluated_count?: number;
}

export interface CurrentQuestion {
  position: number;
  question_count: number;
  media_url: string;
  duration_ms: number;
  authors?: Author[];
  starts_at?: string;
  ends_at?: string;
  grace_seconds?: number;
  selected_author_id?: string | null;
  is_correct?: boolean;
  reaction?: -1 | 1 | null;
  correct_author?: Author;
}

export interface RoomSnapshot {
  room: {
    id: string;
    code: string;
    state: RoomState;
    current_position: number | null;
  };
  pack: { title: string; question_count: number };
  players: Player[];
  scoreboard: ScoreRow[];
  current_question?: CurrentQuestion;
  popular_meme?: { meme_id: string; rating: number; votes: number } | null;
}

export interface ServerEnvelope<T = Record<string, unknown>> {
  type: string;
  request_id?: string;
  server_time: string;
  payload: T;
}

export interface ApiErrorPayload {
  error?: { code: string; message: string };
  detail?: string | Array<{ msg: string }>;
}
