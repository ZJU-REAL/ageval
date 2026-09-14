import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@ageval/shared/components/ui/select";
import { isDraftRelease, versionLabel, type PackageRelease } from "@/lib/api";
import { formatDay } from "@ageval/shared/lib/utils";

function byNewest(versions: PackageRelease[]): PackageRelease[] {
  return [...versions].sort((a, b) => {
    const aDraft = isDraftRelease(a) ? 1 : 0;
    const bDraft = isDraftRelease(b) ? 1 : 0;
    if (aDraft !== bDraft) return bDraft - aDraft;
    return (b.created_at ?? 0) - (a.created_at ?? 0);
  });
}

export function VersionSwitcher({
  versions,
  value,
  onChange,
}: {
  versions: PackageRelease[];
  value: string;
  onChange: (version: string) => void;
}) {
  if (versions.length === 0) return null;
  const ordered = byNewest(versions);
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger
        aria-label="Package version"
        className="h-8 min-w-0 w-auto text-xs"
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent className="w-max min-w-0">
        {ordered.map((row) => (
          <SelectItem
            key={row.version}
            value={row.version}
            trailing={
              row.created_at != null ? formatDay(row.created_at) : undefined
            }
          >
            {versionLabel(row)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
