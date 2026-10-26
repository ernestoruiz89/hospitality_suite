import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { PublicBooking } from "./PublicBooking"
import "./index.css"

createRoot(document.getElementById("root")!).render(
  <StrictMode><PublicBooking /></StrictMode>,
)
