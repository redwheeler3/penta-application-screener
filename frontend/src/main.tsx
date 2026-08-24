import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./App";
import { takeAuthRedirect } from "./authRedirect";
import "./styles.css";
import "./styles/ranking-print.css";
import "./styles/quality-feedback.css";

const authRedirect = takeAuthRedirect();

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App authRedirect={authRedirect} />
  </React.StrictMode>,
);
