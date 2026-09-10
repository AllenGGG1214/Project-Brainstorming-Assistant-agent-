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

export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch('/api' + path, body === undefined ? { cache: 'no-store' } : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status}). Check the input and backend connection.`);
  }
  return response.status === 204 ? undefined as T : response.json();
}
