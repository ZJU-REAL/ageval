import {
  AudioLines,
  ClosedCaption,
  FileText,
  Image,
  LayoutGrid,
  Type,
  Video,
  type LucideIcon,
} from "lucide-react";

import { HoverTip } from "@ageval/shared/components/hover-tip";
import type { ModalityKind, ModalityTab } from "@ageval/shared/lib/model-pin/modalities";
import { cn } from "@ageval/shared/lib/utils";

const ICONS: Record<ModalityKind, LucideIcon> = {
  text: Type,
  image: Image,
  video: Video,
  transcription: ClosedCaption,
  speech: AudioLines,
  pdf: FileText,
};

const TONE: Record<ModalityKind, { fg: string; plate: string }> = {
  text: { fg: "text-mod-text", plate: "bg-mod-text-soft" },
  image: { fg: "text-mod-image", plate: "bg-mod-image-soft" },
  video: { fg: "text-mod-video", plate: "bg-mod-video-soft" },
  transcription: { fg: "text-mod-transcription", plate: "bg-mod-transcription-soft" },
  speech: { fg: "text-mod-speech", plate: "bg-mod-speech-soft" },
  pdf: { fg: "text-mod-pdf", plate: "bg-mod-pdf-soft" },
};

export const MODALITY_BADGE_META: Record<
  ModalityKind,
  { label: string; hint: string }
> = {
  text: {
    label: "Text",
    hint: "Text only.",
  },
  image: {
    label: "Image",
    hint: "Image in input or output.",
  },
  video: {
    label: "Video",
    hint: "Video in input or output.",
  },
  transcription: {
    label: "Transcription",
    hint: "Audio in input.",
  },
  speech: {
    label: "Speech",
    hint: "Audio in output.",
  },
  pdf: {
    label: "PDF",
    hint: "PDF in input or output.",
  },
};

export const MODALITY_TAB_META: {
  id: ModalityTab;
  label: string;
  icon: LucideIcon;
  iconClassName?: string;
}[] = [
  {
    id: "all",
    label: "All",
    icon: LayoutGrid,
    iconClassName: "text-mute group-hover:text-ink group-aria-selected:text-ink",
  },
  {
    id: "text",
    label: "Text",
    icon: Type,
    iconClassName: "text-mute group-hover:text-mod-text group-aria-selected:text-mod-text",
  },
  {
    id: "image",
    label: "Image",
    icon: Image,
    iconClassName: "text-mute group-hover:text-mod-image group-aria-selected:text-mod-image",
  },
  {
    id: "video",
    label: "Video",
    icon: Video,
    iconClassName: "text-mute group-hover:text-mod-video group-aria-selected:text-mod-video",
  },
  {
    id: "pdf",
    label: "PDF",
    icon: FileText,
    iconClassName: "text-mute group-hover:text-mod-pdf group-aria-selected:text-mod-pdf",
  },
  {
    id: "transcription",
    label: "Transcription",
    icon: ClosedCaption,
    iconClassName:
      "text-mute group-hover:text-mod-transcription group-aria-selected:text-mod-transcription",
  },
  {
    id: "speech",
    label: "Speech",
    icon: AudioLines,
    iconClassName: "text-mute group-hover:text-mod-speech group-aria-selected:text-mod-speech",
  },
];

export function ModalityMark({
  kind,
  className,
}: {
  kind: ModalityKind;
  className?: string;
}) {
  const Icon = ICONS[kind];
  const tone = TONE[kind];
  const meta = MODALITY_BADGE_META[kind];
  return (
    <HoverTip content={meta.hint}>
      <span
        className={cn(
          "inline-flex size-6 shrink-0 items-center justify-center rounded-[8px]",
          tone.plate,
          className,
        )}
        aria-label={meta.label}
      >
        <Icon className={cn("size-3.5", tone.fg)} aria-hidden />
      </span>
    </HoverTip>
  );
}

export function ModalityMarks({
  kinds,
  className,
}: {
  kinds: ModalityKind[];
  className?: string;
}) {
  if (kinds.length === 0) return null;
  return (
    <span className={cn("inline-flex items-center gap-1", className)}>
      {kinds.map((kind) => (
        <ModalityMark key={kind} kind={kind} />
      ))}
    </span>
  );
}
