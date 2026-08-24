const MAGIC_LINK_FRAGMENT_KEY = "magic-link";
const GOOGLE_ACCESS_RESULT_KEY = "access";

export type AuthRedirect = {
  magicLinkToken: string | null;
  googleAccessDenied: boolean;
};

export function takeAuthRedirect(): AuthRedirect {
  const query = new URLSearchParams(window.location.search);
  const fragment = new URLSearchParams(window.location.hash.slice(1));
  const magicLinkToken = fragment.get(MAGIC_LINK_FRAGMENT_KEY);
  const googleAccessDenied = query.get(GOOGLE_ACCESS_RESULT_KEY) === "denied";

  if (magicLinkToken) fragment.delete(MAGIC_LINK_FRAGMENT_KEY);
  if (googleAccessDenied) query.delete(GOOGLE_ACCESS_RESULT_KEY);

  if (magicLinkToken || googleAccessDenied) {
    const remainingQuery = query.toString();
    const remainingFragment = fragment.toString();
    const cleanUrl = `${window.location.pathname}${remainingQuery ? `?${remainingQuery}` : ""}${remainingFragment ? `#${remainingFragment}` : ""}`;
    window.history.replaceState(window.history.state, "", cleanUrl);
  }

  return { magicLinkToken, googleAccessDenied };
}
