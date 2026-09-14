import { createContext, useContext, type ReactNode } from "react";

const OverlayRootContext = createContext<HTMLElement | null>(null);

/** Portals (Select / dropdown / tooltip) render inside the open FrameModal. */
export function OverlayRootProvider({
  value,
  children,
}: {
  value: HTMLElement | null;
  children: ReactNode;
}) {
  return (
    <OverlayRootContext.Provider value={value}>{children}</OverlayRootContext.Provider>
  );
}

export function useOverlayRoot(): HTMLElement | undefined {
  return useContext(OverlayRootContext) ?? undefined;
}
