import { Pin, Settings, StickyNote, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@ageval/shared/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@ageval/shared/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@ageval/shared/components/ui/tooltip";
import type { Job } from "@/lib/api";
import type { JobPref } from "@/lib/job-prefs";
import { hasJobNote } from "@/lib/job-prefs";
import { jobDisplayName } from "@/lib/routes";

type Props = {
  job: Job;
  pref: JobPref;
  onPin: () => void;
  onNote: () => void;
  onDelete: () => void;
};

export function JobRowActions({ job, pref, onPin, onNote, onDelete }: Props) {
  const [open, setOpen] = useState(false);
  const noted = hasJobNote(pref);
  const pinned = Boolean(pref.pinned);
  const keepVisible = noted || pinned;
  const name = jobDisplayName(job);
  const icon = noted ? (
    <StickyNote className="h-4 w-4" />
  ) : pinned ? (
    <Pin className="h-4 w-4" />
  ) : (
    <Settings className="h-4 w-4" />
  );

  const trigger = (
    <DropdownMenuTrigger asChild>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        data-job-actions=""
        data-has-note={noted ? "" : undefined}
        data-pinned={pinned && !noted ? "" : undefined}
        aria-label={`Actions for ${name}`}
        aria-haspopup="menu"
        className="h-7 w-7 opacity-0 transition-opacity focus-visible:opacity-100 [@media(hover:none)]:opacity-100"
        style={open || keepVisible ? { opacity: 1 } : undefined}
      >
        {icon}
      </Button>
    </DropdownMenuTrigger>
  );

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      {noted ? (
        <TooltipProvider delayDuration={200}>
          <Tooltip open={open ? false : undefined}>
            <TooltipTrigger asChild>{trigger}</TooltipTrigger>
            <TooltipContent side="left" className="max-w-sm break-all">
              {pref.note}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      ) : (
        trigger
      )}
      <DropdownMenuContent align="end" onCloseAutoFocus={(e) => e.preventDefault()}>
        <DropdownMenuItem
          onSelect={() => {
            onPin();
          }}
        >
          <Pin className="h-3.5 w-3.5" />
          {pref.pinned ? "Unpin" : "Pin"}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={onNote}>
          <StickyNote className="h-3.5 w-3.5" />
          Note
        </DropdownMenuItem>
        <DropdownMenuItem className="text-error focus:text-error" onSelect={onDelete}>
          <Trash2 className="h-3.5 w-3.5" />
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
