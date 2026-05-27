import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "@/App";
import "@/styles/index.css";

// TODO(phase-0.5): wire up TanStack Query provider here (Phase 1+).

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
