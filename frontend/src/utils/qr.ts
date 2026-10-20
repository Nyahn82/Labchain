/** Accept only our opaque token or exact supported report links; never navigate decoded URLs. */
export function reportToken(value: string, origin = window.location.origin): string | null {
  const raw = value.trim();
  if (/^[A-Za-z0-9_-]{43}$/.test(raw)) return raw;
  if (raw.length > 512 || /[\s\\]/.test(raw)) return null;
  try {
    const url = new URL(raw);
    if (url.protocol !== "https:" || url.username || url.password || url.search ||
      !new Set([origin, "https://labchain.online", "https://www.labchain.online"]).has(url.origin)) return null;
    const match = !url.hash ? /^\/api\/v1\/verify\/([A-Za-z0-9_-]{43})$/.exec(url.pathname)
      : url.pathname === "/" ? /^#\/verify\/([A-Za-z0-9_-]{43})$/.exec(url.hash) : null;
    return match?.[1] || null;
  } catch { return null; }
}
