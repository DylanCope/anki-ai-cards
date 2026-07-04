export type ChatRole = "user" | "assistant";

export interface ChatHistoryEntry {
  role: ChatRole;
  text: string;
}

export interface AudioOptionsPayload {
  type: "audio_options";
  text: string | null;
  options: string[];
}

export interface CardPayload {
  type: "card";
  deck_name: string | null;
  model_name: string | null;
  fields: Record<string, string> | null;
  tags: string[] | null;
  note_id: number | null;
}

export type ChatPayload = AudioOptionsPayload | CardPayload;

export interface ChatTurn {
  message: ChatHistoryEntry;
  payloads: ChatPayload[];
}

export interface ChatResponseBody {
  reply: string;
  payloads: ChatPayload[];
}

export interface ChatErrorDetail {
  error: string;
  bug_report_id: number;
}

export interface ChatErrorBody {
  detail: ChatErrorDetail;
}
