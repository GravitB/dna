export const api = async (path: string, init?: RequestInit) => {
  const r = await fetch(`/api${path}`, init);
  const data = await r.json().catch(() => ({}));
  if (!r.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Request failed. Please try again.",
    );
  return data;
};
export const post = (path: string, body = {}) =>
  api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
export const date = (v?: string | null) =>
  v ? new Date(v).toLocaleString() : "Not recorded";
