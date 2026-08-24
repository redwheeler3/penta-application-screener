import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./App";
import { ApplicantApp } from "./applicant/ApplicantApp";
import { takeAuthRedirect } from "./authRedirect";
import { isApplicantSurface } from "./surface";
import "./styles.css";
import "./styles/applicant.css";
import "./styles/ranking-print.css";
import "./styles/quality-feedback.css";

const applicantSurface = isApplicantSurface();

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    {applicantSurface ? <ApplicantApp /> : <App authRedirect={takeAuthRedirect()} />}
  </React.StrictMode>,
);
