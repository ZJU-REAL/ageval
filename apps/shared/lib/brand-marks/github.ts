const LOGIN = /^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$/;
const URL_RE =
  /^(?:https?:\/\/)?(?:www\.)?github\.com\/([A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38})(?:\/|$)/i;

export function parseGithubLogin(raw: string | null | undefined): string | null {
  const text = (raw || "").trim();
  if (!text) return null;
  const fromUrl = text.match(URL_RE);
  const login = (fromUrl?.[1] || (text.startsWith("@") ? text.slice(1) : text)).trim();
  if (!LOGIN.test(login)) return null;
  return login;
}

export function githubAvatarUrl(login: string, size = 64): string {
  return `https://github.com/${encodeURIComponent(login)}.png?size=${size}`;
}
