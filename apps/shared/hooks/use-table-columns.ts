import { useCallback, useState } from "react";

function readStoredColumns<T extends string>(
  key: string,
  allowed: ReadonlySet<T>,
  defaults: readonly T[],
): T[] {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return [...defaults];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [...defaults];
    return parsed.filter(
      (id): id is T => typeof id === "string" && allowed.has(id as T),
    );
  } catch {
    return [...defaults];
  }
}

/** Persist optional table-column ids. `allowed` is the option id list (stable). */
export function useTableColumns<T extends string>(
  storageKey: string,
  allowed: readonly T[],
  defaults: readonly T[],
): [T[], (next: T[]) => void] {
  const [selected, setSelected] = useState<T[]>(() =>
    readStoredColumns(storageKey, new Set(allowed), defaults),
  );

  const setNext = useCallback(
    (next: T[]) => {
      const allow = new Set(allowed);
      const filtered = next.filter((id) => allow.has(id));
      setSelected(filtered);
      try {
        localStorage.setItem(storageKey, JSON.stringify(filtered));
      } catch {
        /* quota / private mode */
      }
    },
    [allowed, storageKey],
  );

  return [selected, setNext];
}
