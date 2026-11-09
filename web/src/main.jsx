// main.jsx: Einstiegspunkt des Dashboards (eigenständige Vite-App, früher Hermes-Plugin)
import React from "react";
import { createRoot } from "react-dom/client";
import { Studio } from "./app/Studio.jsx";

createRoot(document.getElementById("root")).render(<Studio />);
