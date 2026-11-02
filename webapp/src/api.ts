import { getInitData } from "./telegram";

export class ApiError extends Error {
  constructor(public status: number, public code: string) { super(code); }
  get kind(): "network" | "rate" | "auth" | "server" | "other" {
    if (this.status === 0) return "network";
    if (this.status === 429) return "rate";
    if (this.status === 401) return "auth";
    return this.status >= 500 ? "server" : "other";
  }
}

export interface User { id: number; first_name: string; username: string | null; language: "fa" | "en"; is_admin: boolean; points: number; created_at: string }
export interface Song { id: number; title: string; artist: string; genre: string | null; mood: string | null; language_code: string | null; cover_url: string | null; source_url: string | null; is_demo: boolean }
export interface Trend { rank: number; title: string; artist: string | null; region: string; url: string | null; source: string | null }
export interface Feature { key: string; stage: number; available: boolean }
export interface Home { song_of_day: Song | null; song_of_day_basis: string; trending: Trend[]; trending_available: boolean; daily_challenge: unknown | null; suggested: Song[]; suggested_basis: string; features: Feature[]; has_demo_data: boolean }

let token: string | null = null;
export const setToken = (t: string | null) => { token = t; };

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers: { ...(body !== undefined ? { "Content-Type": "application/json" } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch { throw new ApiError(0, "network"); }
  if (res.status === 204) return undefined as T;
  let data: unknown = null;
  try { data = await res.json(); } catch { /* */ }
  if (!res.ok) throw new ApiError(res.status, (data as { error?: string } | null)?.error ?? "error");
  return data as T;
}

export async function login(): Promise<User> {
  const init = getInitData();
  if (!init) throw new ApiError(401, "no_init_data");
  const r = await call<{ access_token: string; user: User }>("POST", "/api/auth/telegram", { init_data: init });
  setToken(r.access_token);
  return r.user;
}
export const getHome = () => call<Home>("GET", "/api/home");
export const setLanguage = (language: "fa" | "en") => call<User>("PATCH", "/api/me", { language });
export const deleteAccount = () => call<void>("DELETE", "/api/me", { confirm: true });
