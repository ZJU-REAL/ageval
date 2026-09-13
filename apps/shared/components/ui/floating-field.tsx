import { useId, type InputHTMLAttributes, type TextareaHTMLAttributes } from "react";

import { cn } from "@ageval/shared/lib/utils";

type Common = {
  label: string;
  className?: string;
};

type InputProps = Common &
  Omit<InputHTMLAttributes<HTMLInputElement>, "placeholder" | "className"> & {
    multiline?: false;
  };

type AreaProps = Common &
  Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "placeholder" | "className"> & {
    multiline: true;
  };

export function FloatingField(props: InputProps | AreaProps) {
  const autoId = useId();
  const id = props.id || autoId;
  const labelClass = cn(
    "pointer-events-none absolute left-2.5 origin-left px-1 text-sm text-mute",
    "motion-safe:transition-[top,transform,color,background-color] motion-safe:duration-200 motion-safe:ease-smooth",
    "peer-focus:bg-canvas peer-focus:text-link peer-focus:top-0 peer-focus:-translate-y-1/2 peer-focus:scale-[0.85]",
    "peer-[:not(:placeholder-shown)]:bg-canvas peer-[:not(:placeholder-shown)]:text-link",
    "peer-[:not(:placeholder-shown)]:top-0 peer-[:not(:placeholder-shown)]:-translate-y-1/2 peer-[:not(:placeholder-shown)]:scale-[0.85]",
    props.multiline ? "top-3" : "top-1/2 -translate-y-1/2",
  );
  const controlClass = cn(
    "peer w-full rounded-[10px] border border-hairline bg-canvas px-3.5 text-sm text-ink shadow-none",
    "placeholder:text-transparent focus-visible:outline-none focus-visible:border-link",
    "disabled:cursor-not-allowed disabled:opacity-50",
    props.multiline ? "min-h-[5.5rem] resize-y py-3" : "h-9",
    props.className,
  );

  if (props.multiline) {
    const { label, className: _c, multiline: _m, ...rest } = props;
    return (
      <div className="relative">
        <textarea id={id} placeholder=" " className={controlClass} {...rest} />
        <label htmlFor={id} className={labelClass}>
          {label}
        </label>
      </div>
    );
  }

  const { label, className: _c, multiline: _m, ...rest } = props;
  return (
    <div className="relative">
      <input id={id} placeholder=" " className={controlClass} {...rest} />
      <label htmlFor={id} className={labelClass}>
        {label}
      </label>
    </div>
  );
}
