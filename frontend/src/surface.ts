export function isApplicantSurface(location: Location = window.location): boolean {
  if (location.hostname === "applications.pentacoop.com") return true;
  if (location.hostname === "applications.localhost") return true;
  return location.hostname === "localhost" && new URLSearchParams(location.search).has("applicant");
}
