// Google Picker integration (M18). Lets an admin pick the response spreadsheet from their
// own Drive after granting the drive.file scope via the backend connect-sheet flow. Only
// admins ever load this — members never touch Google JS.
//
// Flow: the admin has already re-consented (drive.file is in their server-side token). To
// open the Picker we need a browser access token; we get a fresh short-lived one via GIS
// token client (drive.file), open the Picker with it, and return the picked file id. The
// short-lived token is used ONLY to render the Picker — the durable read during sync uses
// the admin's server-side offline token, so this token expiring is harmless.
//
// Requires (Google Cloud, project penta-application-screener):
//   - Google Picker API enabled
//   - a browser API key restricted to the Picker API + our origins  (VITE_GOOGLE_PICKER_API_KEY)
//   - the OAuth web client id                                        (VITE_GOOGLE_CLIENT_ID)

const DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file";
const API_KEY = import.meta.env.VITE_GOOGLE_PICKER_API_KEY as string | undefined;
const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined;

// Minimal shapes for the two Google globals we touch, so we avoid `any` sprawl.
type GapiGlobal = { load: (name: string, cb: () => void) => void };
type PickerResult = { action: string; docs?: Array<{ id: string; name?: string }> };
declare global {
  interface Window {
    gapi?: GapiGlobal;
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

// Get a fresh drive.file access token via GIS. The admin already consented in the backend
// connect-sheet step, so this is a silent/quick grant (prompt: "" reuses the existing grant).
function requestAccessToken(): Promise<string> {
  return new Promise((resolve, reject) => {
    const client = window.google.accounts.oauth2.initTokenClient({
      client_id: CLIENT_ID,
      scope: DRIVE_FILE_SCOPE,
      prompt: "",
      callback: (resp: { access_token?: string; error?: string }) => {
        if (resp.access_token) resolve(resp.access_token);
        else reject(new Error(resp.error || "Could not get Google access token."));
      },
    });
    client.requestAccessToken();
  });
}

function openPicker(accessToken: string): Promise<{ id: string; name?: string } | null> {
  return new Promise((resolve) => {
    const google = window.google;
    const view = new google.picker.DocsView(google.picker.ViewId.SPREADSHEETS)
      .setIncludeFolders(true)
      .setSelectFolderEnabled(false);
    const picker = new google.picker.PickerBuilder()
      .addView(view)
      .setOAuthToken(accessToken)
      .setDeveloperKey(API_KEY)
      .setTitle("Select the response spreadsheet")
      .setCallback((data: PickerResult) => {
        const g = window.google.picker;
        if (data.action === g.Action.PICKED && data.docs?.length) {
          resolve({ id: data.docs[0].id, name: data.docs[0].name });
        } else if (data.action === g.Action.CANCEL) {
          resolve(null);
        }
      })
      .build();
    picker.setVisible(true);
  });
}

/** True only when the browser env is configured for the Picker (both keys present). Lets the
 * UI show a helpful message instead of a broken button when the env vars are missing. */
export function isPickerConfigured(): boolean {
  return Boolean(API_KEY && CLIENT_ID);
}

/** Load Google JS, get a drive.file token, open the Picker, and resolve the picked file
 * (or null if cancelled). Throws on load/token/config failure. Admin-only path. */
export async function pickResponseSheet(): Promise<{ id: string; name?: string } | null> {
  if (!isPickerConfigured()) {
    throw new Error("Google Picker is not configured (missing API key or client id).");
  }
  await Promise.all([
    loadScript("https://apis.google.com/js/api.js"),
    loadScript("https://accounts.google.com/gsi/client"),
  ]);
  // gapi.load('picker') must complete before google.picker exists.
  await new Promise<void>((resolve) => window.gapi!.load("picker", () => resolve()));
  const token = await requestAccessToken();
  return openPicker(token);
}
