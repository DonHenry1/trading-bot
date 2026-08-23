const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
async function request(path) {
  const response = await fetch(`${API_BASE_URL}${path}`, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`API request failed (${response.status})`);
  return response.json();
}
export const api = {
  status: () => request("/api/status"),
  config: () => request("/api/config"),
  portfolio: () => request("/api/portfolio"),
};
