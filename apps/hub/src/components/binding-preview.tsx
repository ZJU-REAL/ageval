import type { ReactNode } from "react";

import { HoverTip } from "@/components/hover-tip";
import { Chip } from "@/components/ui/chip";
import { cn } from "@/lib/utils";

type ExtensionRow = {
  plugin: string;
  options: Record<string, unknown>;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function asString(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return null;
}

function asStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map(asString).filter((item): item is string => Boolean(item));
  }
  const one = asString(value);
  return one ? [one] : [];
}

function asExtensions(value: unknown): ExtensionRow[] {
  if (!Array.isArray(value)) return [];
  const out: ExtensionRow[] = [];
  for (const raw of value) {
    const row = asRecord(raw);
    if (!row) continue;
    const plugin = asString(row.plugin);
    if (!plugin) continue;
    out.push({ plugin, options: asRecord(row.options) || {} });
  }
  return out;
}

function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-x-4 gap-y-1 px-4 py-2.5">
      <div className="pt-0.5 text-sm font-medium text-ink">
        {label}
      </div>
      <div className="min-w-0 text-sm text-ink">{children}</div>
    </div>
  );
}

function OverlayChips({
  paths,
  onOpen,
}: {
  paths: string[];
  onOpen?: (path: string) => void;
}) {
  if (!paths.length) return <span className="text-mute">—</span>;
  return (
    <ul className="m-0 flex min-w-0 flex-wrap gap-x-3 gap-y-1 p-0 list-none">
      {paths.map((path) => {
        const leaf = path.split("/").filter(Boolean).pop() || path;
        const chip = onOpen ? (
          <button
            type="button"
            onClick={() => onOpen(path)}
            className="cursor-pointer text-xs text-ink underline-offset-2 hover:underline hover:decoration-mute"
          >
            {leaf}
          </button>
        ) : (
          <span className="text-xs text-ink">{leaf}</span>
        );
        return (
          <li key={path} className="min-w-0">
            <HoverTip content={path}>{chip}</HoverTip>
          </li>
        );
      })}
    </ul>
  );
}

function ChipList({ items }: { items: string[] }) {
  if (!items.length) return <span className="text-mute">—</span>;
  return (
    <ul className="m-0 flex flex-wrap gap-1 p-0 list-none">
      {items.map((item) => (
        <li key={item}>
          <Chip size="sm">{item}</Chip>
        </li>
      ))}
    </ul>
  );
}

export function BindingPreview({
  binding,
  className,
  onOpenOverlay,
  runModel,
}: {
  binding: Record<string, unknown>;
  className?: string;
  onOpenOverlay?: (path: string) => void;
  /** Selected `?model=` on the Agent page; not package identity. */
  runModel?: string | null;
}) {
  const executor = asString(binding.executor);
  const model = asString(binding.model);
  const override = (runModel || "").trim();
  const modelOverride = override && override !== (model || "");
  const label = asString(binding.label);
  const overlays = asStringList(binding.overlays);
  const extensions = asExtensions(binding.extensions);
  const skip = new Set(["executor", "model", "label", "overlays", "extensions"]);
  const extra = Object.entries(binding).filter(
    ([key, value]) => !skip.has(key) && value != null && value !== "",
  );

  if (
    !executor &&
    !model &&
    !modelOverride &&
    !label &&
    !overlays.length &&
    !extensions.length &&
    extra.length === 0
  ) {
    return <p className="text-sm text-mute">No binding preview available.</p>;
  }

  return (
    <div
      className={cn(
        "blob-panel overflow-hidden",
        className,
      )}
    >
      <div className="divide-y divide-hairline">
        {executor ? (
          <Field label="Executor">
            <span className="text-[13px]">{executor}</span>
          </Field>
        ) : null}
        {model || modelOverride ? (
          <Field label="Model">
            {model ? (
              <span className="text-[13px]">{model}</span>
            ) : (
              <span className="text-mute">—</span>
            )}
            {modelOverride ? (
              <p className="mt-0.5 text-xs text-mute">
                This run overrides to{" "}
                <span className="text-ink">{override}</span> (--model)
              </p>
            ) : null}
          </Field>
        ) : null}
        {label ? (
          <Field label="Label">
            <span className="text-sm text-ink">{label}</span>
          </Field>
        ) : null}
        {overlays.length ? (
          <Field label="Overlays">
            <OverlayChips paths={overlays} onOpen={onOpenOverlay} />
          </Field>
        ) : null}
        {extensions.length ? (
          <Field label="Extensions">
            <ChipList items={extensions.map((ext) => ext.plugin)} />
          </Field>
        ) : null}
        {extra.map(([key, value]) => (
          <Field key={key} label={key}>
            <span className="text-[12px] text-body break-all">
              {typeof value === "string" ? value : JSON.stringify(value)}
            </span>
          </Field>
        ))}
      </div>
    </div>
  );
}
