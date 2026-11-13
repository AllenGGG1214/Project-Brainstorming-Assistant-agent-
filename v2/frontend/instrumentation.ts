// Runs once when the Next.js server boots. On Render's free plan both services sleep,
// so a visitor waking the frontend would otherwise wake the backend only after the
// page loads. Pinging it here makes the two cold starts overlap instead of stacking.
export function register() {
  if (process.env.NEXT_RUNTIME !== 'nodejs') return;
  const origin = (process.env.API_ORIGIN || '').replace(/\/$/, '');
  if (!origin) return;
  fetch(`${origin}/api/health`, { cache: 'no-store' }).catch(() => undefined);
}
