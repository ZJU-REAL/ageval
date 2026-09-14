import { useEffect, useId, useState } from "react";

import { Button } from "@ageval/shared/components/ui/button";
import { toast } from "@ageval/shared/components/ui/toast";
import { Textarea } from "@ageval/shared/components/ui/textarea";
import type { Job } from "@/lib/api";
import { jobDisplayName } from "@/lib/routes";

const NOTE_MAX = 2000;

type Props = {
  job: Job;
  initialNote: string;
  onClose: () => void;
  onSave: (note: string) => void;
};

export function JobNoteDialog({ job, initialNote, onClose, onSave }: Props) {
  const [text, setText] = useState(initialNote);
  const titleId = useId();

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function submit() {
    onSave(text.trim());
    toast("Note saved");
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
      role="presentation"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="w-full max-w-lg rounded-[14px] border border-hairline bg-canvas shadow-[var(--viewer-shadow-pop)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-hairline px-4 py-3">
          <h2 id={titleId} className="text-sm font-medium text-ink">
            Note
          </h2>
          <p className="mt-1 text-xs text-mute truncate">
            {jobDisplayName(job)}
          </p>
        </div>
        <div className="px-4 py-3 space-y-2">
          <Textarea
            autoFocus
            value={text}
            maxLength={NOTE_MAX}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                e.preventDefault();
                submit();
              }
            }}
            placeholder="Local note for this browser. Not written to evidence."
            aria-label="Job note"
          />
          <p className="text-xs text-mute tabular">
            {text.length}/{NOTE_MAX} · stays in this browser
          </p>
        </div>
        <div className="flex justify-end gap-2 border-t border-hairline px-4 py-3">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" onClick={submit}>
            Save
          </Button>
        </div>
      </div>
    </div>
  );
}
