import type { ReactNode } from "react";

export function Outcome({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div>
      <div className="text-xs text-mute mb-0.5">{label}</div>
      <div className="text-sm">{children}</div>
    </div>
  );
}
