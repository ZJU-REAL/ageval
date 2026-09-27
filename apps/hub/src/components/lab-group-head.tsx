import { ArrowUpRight } from "lucide-react";

import { LabMark } from "@ageval/shared/components/lab-mark";
import { EXTERNAL_LINK_CLASS } from "@ageval/shared/lib/links";
import { LAB_INFO } from "@ageval/shared/lib/model-pin";

export function LabGroupHead({
  lab,
  name,
  count,
}: {
  lab: string;
  name: string;
  count: number;
}) {
  const info = lab ? LAB_INFO[lab] : undefined;
  return (
    <div className="flex items-center gap-2">
      {lab ? <LabMark lab={lab} size={22} /> : null}
      <h3 className="text-base font-semibold text-ink">
        {info?.website ? (
          <a
            href={info.website}
            target="_blank"
            rel="noreferrer"
            title={info.website}
            className={`inline-flex items-center gap-1 ${EXTERNAL_LINK_CLASS}`}
          >
            {name}
            <ArrowUpRight className="size-3 text-mute" aria-hidden />
          </a>
        ) : (
          name
        )}
      </h3>
      {info?.description ? (
        <span className="hidden min-w-0 flex-1 truncate text-sm text-mute sm:block">
          {info.description}
        </span>
      ) : null}
      <span className="ml-auto text-xs text-mute tabular-nums">{count}</span>
    </div>
  );
}
