// Google Picker integration (M18). Lets an admin pick the response spreadsheet from their own
// Drive. Only admins ever load this — members never touch Google JS.
//
// Auth uses the GIS CODE MODEL, and this matters: a file picked in the Picker is only
// drive.file-authorized against a token from an INTERACTIVE grant. A server-refreshed token
// does NOT register the picked-file grant (verified the hard way). So the flow is, in one
// user gesture:
//   1. GIS initCodeClient(popup) -> user consents -> we get an auth CODE.
//   2. POST the code to the backend, which exchanges it for a refresh token (durable sync,
//      stored as the reader) AND returns the interactive ACCESS token.
//   3. Open the Picker with THAT access token -> the picked file is properly authorized.
//
// Requires (Google Cloud, project penta-application-screener):
//   - Google Picker API enabled
//   - a browser API key restricted to the Picker API + our origins  (VITE_GOOGLE_PICKER_API_KEY)
//   - the OAuth web client id                                        (VITE_GOOGLE_CLIENT_ID)

import { apiBaseUrl } from "./constants";

const DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file";
const API_KEY = import.meta.env.VITE_GOOGLE_PICKER_API_KEY as string | undefined;
const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined;
// The Cloud project NUMBER — REQUIRED by the Picker (setAppId) for the drive.file scope to
// actually authorize a picked file. Without it, the Picker shows files but selecting one
// registers no grant, so reading it 403s. (The numeric prefix of the OAuth client id.)
const PROJECT_NUMBER = import.meta.env.VITE_GOOGLE_PROJECT_NUMBER as string | undefined;

type PickerResult = { action: string; docs?: Array<{ id: string; name?: string }> };
declare global {
  interface Window {
    gapi?: { load: (name: string, cb: () => void) => void };
    google?: any; // google.accounts.oauth2 (GIS) + google.picker
  }
}

// Load a script once, resolving when ready. Cached by src so repeated opens don't re-inject.
const loaded = new Map<string, Promise<void>>();
function loadScript(src: string): Promise<void> {
  if (!loaded.has(src)) {
    loaded.set(
      src,
      new Promise<void>((resolve, reject) => {
        const el = document.createElement("script");
        el.src = src;
        el.async = true;
        el.onload = () => resolve();
        el.onerror = () => reject(new Error(`Failed to load ${src}`));
        document.head.appendChild(el);
      }),
    );
  }
  return loaded.get(src)!;
}

// Step 1: GIS code client (popup) — must be called from a user gesture. Resolves the auth code.
function requestAuthCode(): Promise<string> {
  return new Promise((resolve, reject) => {
    const client = window.google.accounts.oauth2.initCodeClient({
      client_id: CLIENT_ID,
      scope: DRIVE_FILE_SCOPE,
      ux_mode: "popup",
      callback: (resp: { code?: string; error?: string }) => {
        if (resp.code) resolve(resp.code);
        else reject(new Error(resp.error || "Google authorization was cancelled."));
      },
    });
    client.requestCode();
  });
}

// Step 2: hand the code to the backend, which exchanges it (stores the refresh token as the
// reader) and returns the interactive access token for the Picker.
async function exchangeCodeForToken(code: string): Promise<string> {
  const res = await fetch(`${apiBaseUrl}/settings/exchange-sheet-code`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  if (!res.ok) throw new Error("Couldn't complete Google authorization. Please try again.");
  const body = (await res.json()) as { accessToken?: string };
  if (!body.accessToken) throw new Error("Google authorization returned no access token.");
  return body.accessToken;
}

// Step 3: open the Picker with the interactive access token.
function openPicker(accessToken: string): Promise<{ id: string; name?: string } | null> {
  return new Promise((resolve) => {
    const google = window.google;
    const view = new google.picker.DocsView(google.picker.ViewId.SPREADSHEETS)
      .setMode(google.picker.DocsViewMode.LIST) // list view — easier to scan than icons
      .setIncludeFolders(true)
      .setSelectFolderEnabled(false);
    const builder = new google.picker.PickerBuilder()
      .addView(view)
      .setOAuthToken(accessToken)
      .setDeveloperKey(API_KEY)
      .setTitle("Select the response spreadsheet");
    // setAppId is REQUIRED for drive.file — it's what makes a picked file authorized for the
    // app. Skip only if unconfigured (falls back to the pre-setAppId behaviour).
    if (PROJECT_NUMBER) builder.setAppId(PROJECT_NUMBER);
    const picker = builder
      .setCallback((data: PickerResult) => {
        const g = window.google.picker;
        if (data.action === g.Action.PICKED && data.docs?.length) {
          disposePicker(picker);
          resolve({ id: data.docs[0].id, name: data.docs[0].name });
        } else if (data.action === g.Action.CANCEL) {
          disposePicker(picker);
          resolve(null);
        }
      })
      .build();
    picker.setVisible(true);
    centerPicker();
  });
}

// The Picker renders position:absolute anchored to the DOCUMENT, so when the page is scrolled
// it opens partly off-screen, and it leaves orphan overlay nodes on close. Force it to
// position:fixed + centered (viewport-anchored, correct at any scroll), and sweep leftovers.
function centerPicker(): void {
  let tries = 0;
  const place = () => {
    const dialog = document.querySelector<HTMLElement>(".picker-dialog");
    const bg = document.querySelector<HTMLElement>(".picker-dialog-bg");
    if (dialog) {
      dialog.style.position = "fixed";
      dialog.style.top = "50%";
      dialog.style.left = "50%";
      dialog.style.transform = "translate(-50%, -50%)";
      dialog.style.margin = "0";
    }
    if (bg) {
      bg.style.position = "fixed";
      bg.style.top = "0";
      bg.style.left = "0";
    }
    if (!dialog && tries++ < 20) requestAnimationFrame(place);
  };
  requestAnimationFrame(place);
}

function disposePicker(picker: { dispose?: () => void }): void {
  try {
    picker.dispose?.();
  } catch {
    /* dispose is best-effort */
  }
  document
    .querySelectorAll(".picker-dialog, .picker-dialog-bg")
    .forEach((node) => node.remove());
}

/** True only when the browser env is configured for the Picker (API key + client id). */
export function isPickerConfigured(): boolean {
  return Boolean(API_KEY && CLIENT_ID);
}

/** The whole one-gesture flow: GIS code grant -> backend exchange -> open Picker -> resolve the
 * picked file (or null if cancelled). MUST be called from a user click (GIS opens a popup).
 * Throws on config/auth/load failure. Admin-only. */
export async function pickResponseSheet(): Promise<{ id: string; name?: string } | null> {
  if (!isPickerConfigured()) {
    throw new Error("Google Picker is not configured (missing API key or client id).");
  }
  // Load both Google scripts up front (GIS for the code client, api.js for the Picker).
  await Promise.all([
    loadScript("https://accounts.google.com/gsi/client"),
    loadScript("https://apis.google.com/js/api.js"),
  ]);
  const code = await requestAuthCode(); // popup — inside the user gesture
  const accessToken = await exchangeCodeForToken(code);
  await new Promise<void>((resolve) => window.gapi!.load("picker", () => resolve()));
  return openPicker(accessToken);
}
