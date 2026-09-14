import { Check, Pencil, X } from "lucide-react";
import { useEffect, useState } from "react";

import { HoverTip } from "@ageval/shared/components/hover-tip";
import { Button } from "@ageval/shared/components/ui/button";
import { FloatingField } from "@ageval/shared/components/ui/floating-field";
import { toast } from "@ageval/shared/components/ui/toast";
import { toastError } from "@/lib/toast-error";

export function DescriptionEditor({
  value,
  canEdit,
  maxLength,
  emptyLabel = "No description",
  addLabel = "Add a description",
  onSave,
}: {
  value: string;
  canEdit: boolean;
  maxLength: number;
  emptyLabel?: string;
  addLabel?: string;
  onSave: (next: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  const text = value.trim();

  async function submit() {
    const next = draft.replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();
    if (next === text) {
      setEditing(false);
      return;
    }
    setBusy(true);
    try {
      await onSave(next);
      setEditing(false);
      toast("Description saved");
    } catch (err) {
      toastError(err);
    } finally {
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <form
        className="flex max-w-xl flex-col gap-1.5"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <FloatingField
          multiline
          label="Description"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          maxLength={maxLength}
          autoFocus
          disabled={busy}
        />
        <div className="flex items-center gap-1.5">
          <p className="mr-auto font-mono text-[11px] tabular-nums text-mute">
            {draft.length}/{maxLength}
          </p>
          <Button
            type="submit"
            size="icon"
            variant="secondary"
            disabled={busy}
            aria-label="Save"
            className="h-8 w-8 shrink-0"
          >
            <Check className="size-4" />
          </Button>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            disabled={busy}
            aria-label="Cancel"
            className="h-8 w-8 shrink-0"
            onClick={() => {
              setDraft(value);
              setEditing(false);
            }}
          >
            <X className="size-4" />
          </Button>
        </div>
      </form>
    );
  }

  if (!text && !canEdit) {
    if (!emptyLabel) return null;
    return <p className="text-sm text-mute">{emptyLabel}</p>;
  }

  return (
    <div className="flex max-w-xl items-start gap-1.5">
      <p className={text ? "text-sm text-body whitespace-pre-wrap" : "text-sm text-mute"}>
        {text || addLabel}
      </p>
      {canEdit ? (
        <HoverTip content="Edit description">
          <button
            type="button"
            className="inline-flex shrink-0 rounded-[8px] p-1 text-mute hover:text-body hover:bg-liquid-hover"
            aria-label="Edit description"
            onClick={() => setEditing(true)}
          >
            <Pencil className="size-4" strokeWidth={1.75} />
          </button>
        </HoverTip>
      ) : null}
    </div>
  );
}
