import { toast } from "@ageval/shared/components/ui/toast";
import { RegistryHttpError } from "@/lib/api";

/** Action failure: Hub toast, not a raw ``code: message`` dump in the form. */
export function toastError(err: unknown) {
  const message =
    err instanceof RegistryHttpError
      ? err.message
      : err instanceof Error
        ? err.message
        : String(err);
  toast(message.trim() || "Request failed", { tone: "error" });
}
