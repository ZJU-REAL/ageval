import { Check, Monitor, Moon, Sun } from "lucide-react";

import { Button } from "@ageval/shared/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@ageval/shared/components/ui/dropdown-menu";
import { type ThemeMode, useTheme } from "@ageval/shared/lib/theme";
import { cn } from "@ageval/shared/lib/utils";

const OPTIONS: {
  mode: ThemeMode;
  label: string;
  icon: typeof Sun;
}[] = [
  { mode: "light", label: "Light", icon: Sun },
  { mode: "dark", label: "Dark", icon: Moon },
  { mode: "system", label: "System", icon: Monitor },
];

export function ThemeToggle() {
  const { mode, setMode, resolved } = useTheme();
  const ActiveIcon = mode === "system" ? Monitor : resolved === "dark" ? Moon : Sun;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={`Theme: ${mode}`}
          className="cursor-pointer text-mute hover:text-ink"
        >
          <ActiveIcon className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[9.5rem]">
        {OPTIONS.map(({ mode: m, label, icon: Icon }) => (
          <DropdownMenuItem
            key={m}
            onSelect={() => setMode(m)}
            className={cn(mode === m && "bg-canvas-soft")}
          >
            <Icon className="h-4 w-4 text-mute" />
            <span className="flex-1">{label}</span>
            {mode === m ? <Check className="h-3.5 w-3.5 text-ink" /> : null}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
