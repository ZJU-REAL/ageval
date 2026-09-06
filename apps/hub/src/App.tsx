import { BrowserRouter } from "react-router-dom";

import { Shell } from "@/components/layout";
import { HubRoutes } from "@/hub-routes";

export default function App() {
  return (
    <BrowserRouter useTransitions={false}>
      {/* RR7 wraps location in startTransition by default; URL can move while the tree stays put. */}
      <Shell>
        <HubRoutes />
      </Shell>
    </BrowserRouter>
  );
}
