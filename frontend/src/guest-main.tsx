import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { GuestPortal } from "./GuestPortal"
import "./index.css"

createRoot(document.getElementById("root")!).render(
  <StrictMode><GuestPortal /></StrictMode>,
)
