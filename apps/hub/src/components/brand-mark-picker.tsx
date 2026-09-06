import { useEffect, useMemo, useState } from "react";

import { BrandMark } from "@/components/brand-mark";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { buttonVariants } from "@/components/ui/button";
import {
  BRAND_MARKS,
  FIRST_PARTY_MARK_ID,
  githubAvatarUrl,
  parseGithubLogin,
} from "@/lib/brand-marks";
import { cn } from "@/lib/utils";

export type MarkDraft =
  | { mode: "default" }
  | { mode: "catalog"; id: string }
  | { mode: "github"; login: string };

export function BrandMarkPicker({
  open,
  current,
  uploadedBy,
  firstParty = false,
  defaultLetter,
  busy = false,
  onCancel,
  onSave,
}: {
  open: boolean;
  current: MarkDraft;
  uploadedBy?: string | null;
  /** Official / builtin packages default to the bundled first-party mark. */
  firstParty?: boolean;
  defaultLetter?: string;
  busy?: boolean;
  onCancel: () => void;
  onSave: (draft: MarkDraft) => void;
}) {
  const [query, setQuery] = useState("");
  const [githubDraft, setGithubDraft] = useState("");
  const [selected, setSelected] = useState<MarkDraft>(current);

  useEffect(() => {
    if (!open) return;
    setSelected(current);
    setQuery("");
    setGithubDraft(current.mode === "github" ? current.login : "");
  }, [open, current]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return BRAND_MARKS;
    return BRAND_MARKS.filter(
      (row) => row.id.includes(q) || row.label.toLowerCase().includes(q),
    );
  }, [query]);

  const uploader = parseGithubLogin(uploadedBy || "");
  const githubLogin = parseGithubLogin(githubDraft);
  const githubInvalid = Boolean(githubDraft.trim()) && !githubLogin;

  return (
    <ConfirmDialog
      open={open}
      title="Choose icon"
      description="Search the catalog, or paste a GitHub profile / org URL."
      confirmLabel="Save"
      confirmVariant="default"
      busy={busy}
      confirmDisabled={selected.mode === "github" && !githubLogin}
      className="max-w-lg"
      onCancel={onCancel}
      onConfirm={() => {
        if (selected.mode === "github") {
          if (!githubLogin) return;
          onSave({ mode: "github", login: githubLogin });
          return;
        }
        onSave(selected);
      }}
    >
      <Input
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search catalog"
        aria-label="Search icons"
        className="mb-3"
        autoFocus
      />
      <div className="grid max-h-56 grid-cols-4 gap-1.5 overflow-auto sm:grid-cols-5">
        <button
          type="button"
          onClick={() => setSelected({ mode: "default" })}
          className={cn(
            buttonVariants({ variant: "secondary" }),
            "h-auto flex-col gap-1 rounded-[12px] px-2 py-2 text-center",
            selected.mode === "default" && "bg-canvas-soft-2 shadow-[var(--viewer-shadow-pop)]",
          )}
        >
          <BrandMark
            mark={
              firstParty
                ? { kind: "catalog", id: FIRST_PARTY_MARK_ID }
                : uploader
                  ? {
                      kind: "github",
                      login: uploader,
                      src: githubAvatarUrl(uploader),
                    }
                  : { kind: "letter", letter: defaultLetter || "?" }
            }
            size={20}
          />
          <span className="text-[10px] text-mute">Default</span>
        </button>
        {rows.map((row) => (
          <button
            type="button"
            key={row.id}
            onClick={() => setSelected({ mode: "catalog", id: row.id })}
            className={cn(
              buttonVariants({ variant: "secondary" }),
              "h-auto flex-col gap-1 rounded-[12px] px-2 py-2 text-center",
              selected.mode === "catalog" &&
                selected.id === row.id &&
                "bg-canvas-soft-2 shadow-[var(--viewer-shadow-pop)]",
            )}
          >
            <BrandMark mark={{ kind: "catalog", id: row.id }} size={20} />
            <span className="w-full truncate text-[10px] text-body">
              {row.label}
            </span>
          </button>
        ))}
      </div>
      <label className="mt-3 block text-xs text-mute">
        GitHub link
        <Input
          value={githubDraft}
          onChange={(event) => {
            const next = event.target.value;
            setGithubDraft(next);
            const login = parseGithubLogin(next);
            if (login) setSelected({ mode: "github", login });
          }}
          placeholder="https://github.com/octocat"
          aria-label="GitHub profile or organization URL"
          className="mt-1"
        />
      </label>
      {githubInvalid ? (
        <p className="mt-1 text-xs text-error">Need a GitHub login or github.com/login URL</p>
      ) : null}
    </ConfirmDialog>
  );
}
