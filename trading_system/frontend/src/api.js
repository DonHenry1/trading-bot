const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: { Accept: "application/json", ...(options.headers || {}) },
  });

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch (_) {
      // Keep the HTTP status as the useful fallback.
    }
    throw new Error(detail);
  }
  return response.json();
}

export const api = {
  health: () => request("/health"),
  status: () => request("/api/status"),
  config: () => request("/api/config"),
  portfolio: () => request("/api/portfolio"),
  positions: () => request("/api/positions"),
  events: () => request("/api/events"),
  equity: () => request("/api/equity"),
};
