import type { UpdateInfo } from "../shared/contracts";

const REPO = "nwmwkskw905-collab/WSRn";

export async function checkForUpdates(current: string): Promise<UpdateInfo> {
  const base: UpdateInfo = {
    current,
    latest: null,
    updateAvailable: false,
    url: `https://github.com/${REPO}/releases`,
    signature: "not_configured",
  };
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    const response = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, {
      headers: { Accept: "application/vnd.github+json", "User-Agent": "JARVIS-AI" },
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!response.ok) {
      return { ...base, error: `GitHub HTTP ${response.status}` };
    }
    const data: any = await response.json();
    const latest = String(data.tag_name || "").replace(/^v/, "") || null;
    const updateAvailable = Boolean(latest && compareVersions(latest, current) > 0);
    return {
      ...base,
      latest,
      updateAvailable,
      url: data.html_url || base.url,
      publishedAt: data.published_at,
      notes: (data.body || "").slice(0, 4000),
      signature: "not_configured",
    };
  } catch (error) {
    return { ...base, error: String(error) };
  }
}

function compareVersions(a: string, b: string): number {
  const pa = a.split(".").map((n) => parseInt(n, 10) || 0);
  const pb = b.split(".").map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    const diff = (pa[i] || 0) - (pb[i] || 0);
    if (diff !== 0) return diff;
  }
  return 0;
}
