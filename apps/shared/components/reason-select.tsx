import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@ageval/shared/components/ui/select";

export function ReasonSelect({
  value,
  reasons,
  onChange,
}: {
  value: string;
  reasons: readonly string[];
  onChange: (next: string) => void;
}) {
  if (reasons.length === 0) return null;
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger aria-label="Filter by reason" className="w-[16rem] max-w-full">
        <SelectValue placeholder="All reasons" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="all">All reasons</SelectItem>
        {reasons.map((reason) => (
          <SelectItem key={reason} value={reason}>
            {reason}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
