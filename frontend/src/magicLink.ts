const MAGIC_LINK_FRAGMENT_KEY = "magic-link";

export function takeMagicLinkToken(): string | null {
  const fragment = new URLSearchParams(window.location.hash.slice(1));
  const token = fragment.get(MAGIC_LINK_FRAGMENT_KEY);
  if (!token) return null;

  fragment.delete(MAGIC_LINK_FRAGMENT_KEY);
  const remainingFragment = fragment.toString();
  const cleanUrl = `${window.location.pathname}${window.location.search}${remainingFragment ? `#${remainingFragment}` : ""}`;
  window.history.replaceState(window.history.state, "", cleanUrl);
  return token;
}
