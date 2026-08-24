import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./App";
import { takeMagicLinkToken } from "./magicLink";
import "./styles.css";
import "./styles/ranking-print.css";
import "./styles/quality-feedback.css";

const initialMagicLinkToken = takeMagicLinkToken();

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App initialMagicLinkToken={initialMagicLinkToken} />
  </React.StrictMode>,
);
