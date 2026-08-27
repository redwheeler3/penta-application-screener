import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";

import { takeAuthRedirect } from "./authRedirect";
import { isApplicantSurface } from "./surface";
import "./styles.css";
import "./styles/applicant.css";
import "./styles/ranking-print.css";
import "./styles/quality-feedback.css";

const applicantSurface = isApplicantSurface();
const accessPreview = import.meta.env.DEV
  && new URLSearchParams(window.location.search).get("preview") === "access";
const authRedirect = takeAuthRedirect();
document.title = accessPreview
  ? "Penta Housing Co-Op | Access Preview"
  : applicantSurface
    ? "Penta Housing Co-Op | Application for Membership"
    : "Penta Housing Co-Op | Application Screener";
const AccessPreviewGallery = lazy(() =>
  import("./previews/AccessPreviewGallery").then(({ AccessPreviewGallery }) => ({
    default: AccessPreviewGallery,
  })),
);
const ApplicantApp = lazy(() =>
  import("./applicant/ApplicantApp").then(({ ApplicantApp }) => ({ default: ApplicantApp })),
);
const CommitteeApp = lazy(() =>
  import("./App").then(({ App }) => ({
    default: () => <App authRedirect={authRedirect} />,
  })),
);

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <Suspense fallback={null}>
      {accessPreview ? <AccessPreviewGallery /> : applicantSurface ? <ApplicantApp /> : <CommitteeApp />}
    </Suspense>
  </React.StrictMode>,
);
