export type ChatRole = "user" | "assistant";

export interface Conversation {
  id: number;
  title: string | null;
  model: string;
  created_at: string;
  updated_at: string;
}

export interface ModelInfo {
  id: string;
  provider: "anthropic" | "gemini";
  display_name: string;
  input_price_per_mtok: number;
  output_price_per_mtok: number;
  description: string;
}

export interface ChatHistoryEntry {
  role: ChatRole;
  text: string;
}

export interface ChatHistoryResponseEntry extends ChatHistoryEntry {
  payloads: ChatPayload[];
}

export interface AudioOptionsPayload {
  type: "audio_options";
  text: string | null;
  clip_ids: number[];
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

export interface ImageOptionsPayload {
  type: "image_options";
  query_or_prompt: string | null;
  image_ids: number[];
  options: string[];
  content_types: string[];
}

export type ChatPayload = AudioOptionsPayload | CardPayload | ImageOptionsPayload;

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

export interface WorkflowSpec {
  name: string;
  spec: string;
  created_at: string;
  updated_at: string;
}
