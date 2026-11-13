export const stages = ['organize', 'research', 'functions', 'prototype', 'architecture'] as const;
export type Stage = typeof stages[number];
export const stageLabels = ['Idea brief', 'Research & decision', 'Function plan', 'Interactive prototype', 'Architecture'];
export const stageDescriptions = ['Clarify the problem, users, and boundaries', 'Validate the direction with sources and comparisons', 'Turn scope into functions and effort', 'Experience the flow before choosing implementation', 'Connect requirements, components, and delivery'];
export type FunctionItem = { id: string; name: string; value: string; requirement: string; tier: string; dependencies: string[]; low_days: number; likely_days: number; high_days: number; risk: string };
export type Content = {
  markdown: string; assumptions?: string[]; search_terms?: string[];
  recommendation?: string; rationale?: string; uncertainty?: string[];
  comparisons?: { name: string; overlap: string; difference: string; evidence: string; source_urls: string[] }[];
  functions?: FunctionItem[]; daily_rate?: number; currency?: string;
  html?: string; mappings?: { function_id: string; implementation: string; behavior: string }[];
  mermaid?: string; components?: { name: string; function_ids: string[]; responsibility: string }[];
  tradeoffs?: string[];
};
export type Artifact = { id: string; stage: Stage; version: number; valid: number; approved_at: string | null; decision: string | null; created_at: string; content: Content; metadata: { mode: string; model?: string; sources: { url: string; title: string }[]; queries?: string[]; searched_at?: string; search_text?: string } };
export type Run = { id: string; stage: Stage; status: string; error: string | null; created_at: string };
export type Project = { id: string; title: string; idea: string; constraints: string; mode: 'demo' | 'live'; decision: string | null; created_at: string; updated_at: string; artifacts: Artifact[]; runs: Run[] };
export type ProjectSummary = Omit<Project, 'artifacts' | 'runs'> & { accepted_count: number };
export type Health = { live_available: boolean; model: string; auth_required: boolean };
export type AuthStatus = { required: boolean; authenticated: boolean; registration_enabled: boolean; user: { email: string } | null };

// Render free services sleep when idle and can take 60-120 s to wake.
const coldStartWindowMs = 180_000;
const retryDelayMs = 3000;
const attemptTimeoutMs = 25_000;
const retryableStatuses = new Set([502, 503, 504]);

function wait(milliseconds: number) {
  return new Promise(resolve => setTimeout(resolve, milliseconds));
}

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) { super(message); }
}

export async function api<T>(path: string, body?: unknown): Promise<T> {
  const options: RequestInit = body === undefined
    ? { cache: 'no-store' }
    : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  let response: Response | undefined;
  let networkError: unknown;

  // Retry reads only: replaying a POST could create duplicate projects, runs, or approvals.
  const deadline = Date.now() + coldStartWindowMs;
  for (;;) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), attemptTimeoutMs);
    try {
      response = await fetch('/api' + path, { ...options, signal: body === undefined ? controller.signal : undefined });
      networkError = undefined;
      if (body !== undefined || !retryableStatuses.has(response.status)) break;
    } catch (error) {
      networkError = error;
      response = undefined;
      if (body !== undefined) break;
    } finally {
      clearTimeout(timer);
    }
    if (Date.now() + retryDelayMs >= deadline) break;
    await wait(retryDelayMs);
  }

  if (!response) {
    throw networkError instanceof Error ? networkError : new Error('Cannot reach the backend.');
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status}). Check the input and backend connection.`, response.status);
  }
  return response.status === 204 ? undefined as T : response.json();
}
