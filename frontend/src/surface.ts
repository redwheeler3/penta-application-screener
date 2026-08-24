export function isApplicantSurface(location: Location = window.location): boolean {
  if (location.hostname === "applications.pentacoop.com") return true;
  if (location.hostname === "applications.localhost") return true;
  if (new URLSearchParams(location.hash.slice(1)).has("applicant-link")) return true;
  return location.hostname === "localhost" && new URLSearchParams(location.search).has("applicant");
}
