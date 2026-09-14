import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { ThemeProvider } from "@ageval/shared/lib/theme";
import "./index.css";

try {
  const stored = localStorage.getItem("ageval-hub-theme");
  const mode =
    stored === "light" || stored === "dark" || stored === "system"
      ? stored
      : "system";
  document.documentElement.setAttribute("data-theme", mode);
  const dark =
    mode === "dark" ||
    (mode === "system" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
} catch {
  document.documentElement.setAttribute("data-theme", "system");
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider storageKey="ageval-hub-theme">
      <App />
    </ThemeProvider>
  </StrictMode>,
);
