export type ToastTone = "ok" | "error" | "warn" | "tip";

export type ToastInput = {
  message: string;
  tone?: ToastTone;
  duration?: number;
};

type Listener = (input: ToastInput) => void;

let listener: Listener | null = null;

export function toast(message: string, opts?: Omit<ToastInput, "message">) {
  listener?.({ message, ...opts });
}

export function bindToast(next: Listener | null) {
  listener = next;
}
