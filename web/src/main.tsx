import { render } from "@solidjs/web"
import { App } from "./App"
import "./style.css"
import "./live.css"

const root = document.getElementById("root")
if (root) render(() => <App />, root)
