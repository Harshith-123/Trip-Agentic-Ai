const DEFAULT_API_BASE = 'http://localhost:8000';

function apiBase(): string {
  return (process.env.NEXT_PUBLIC_API_BASE_URL || DEFAULT_API_BASE).replace(/\/$/, '');
}

export function apiUrl(path: string): string {
  if (process.env.NEXT_PUBLIC_API_BASE_URL) {
    return `${apiBase()}${path}`;
  }
  return path;
}

export function wsUrl(path: string): string {
  const configured = process.env.NEXT_PUBLIC_WS_BASE_URL;
  const base = (configured || apiBase()).replace(/\/$/, '');
  const wsBase = base.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:');
  return `${wsBase}${path}`;
}
