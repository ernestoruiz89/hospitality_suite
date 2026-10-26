import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { PublicConfirmation } from "./PublicConfirmation"
import "./index.css"

createRoot(document.getElementById("root")!).render(
  <StrictMode><PublicConfirmation /></StrictMode>,
)
