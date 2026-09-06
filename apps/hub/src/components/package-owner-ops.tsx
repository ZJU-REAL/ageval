import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast";
import { toastError } from "@/lib/toast-error";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  deletePackageRelease,
  isDraftRelease,
  releasePackageDraft,
  setPackageVisibility,
  versionLabel,
  type PackageRelease,
} from "@/lib/api";

export function PackageOwnerOps({
  packageId,
  release,
  canManage,
  token,
  onUpdated,
  onDeleted,
  onReleased,
}: {
  packageId: string;
  release: PackageRelease;
  canManage: boolean;
  token: string | null;
  onUpdated: (next: PackageRelease) => void;
  onDeleted: () => void;
  onReleased: (next: PackageRelease) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [releaseOpen, setReleaseOpen] = useState(false);
  const [releaseVisibility, setReleaseVisibility] = useState<
    "public" | "private"
  >(release.visibility === "public" ? "public" : "private");
  const [releaseVersion, setReleaseVersion] = useState("");
  const [replace, setReplace] = useState(false);
  const draft = isDraftRelease(release);
  const label = versionLabel(release);

  if (!canManage || !token) return null;

  function fail(err: unknown) {
    toastError(err);
  }

  async function changeVisibility(next: "public" | "private") {
    if (next === release.visibility) return;
    setBusy(true);
    try {
      const updated = await setPackageVisibility(
        packageId,
        release.version,
        next,
        token,
      );
      onUpdated({ ...release, ...updated, visibility: next });
      toast(`Visibility set to ${next}`);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await deletePackageRelease(packageId, release.version, token);
      setDeleteOpen(false);
      toast("Version deleted");
      onDeleted();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function promote() {
    setBusy(true);
    try {
      const updated = await releasePackageDraft(
        packageId,
        {
          visibility: releaseVisibility,
          version: releaseVersion.trim() || undefined,
          replace: replace || undefined,
        },
        token,
      );
      setReleaseOpen(false);
      toast("Draft released");
      onReleased(updated);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {draft ? (
        <Button
          type="button"
          size="sm"
          disabled={busy}
          onClick={() => {
            setReleaseOpen(true);
            setReleaseVisibility(
              release.visibility === "public" ? "public" : "private",
            );
          }}
        >
          Release draft
        </Button>
      ) : (
        <Select
          value={release.visibility === "public" ? "public" : "private"}
          onValueChange={(value) => {
            if (value === "public" || value === "private") {
              void changeVisibility(value);
            }
          }}
          disabled={busy}
        >
          <SelectTrigger
            aria-label="Package visibility"
            className="h-8 min-w-0 w-auto text-xs"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="public">public</SelectItem>
            <SelectItem value="private">private</SelectItem>
          </SelectContent>
        </Select>
      )}
      <Button
        type="button"
        size="sm"
        variant="dangerOutline"
        disabled={busy}
        onClick={() => {
          setDeleteOpen(true);
        }}
      >
        Delete version
      </Button>
      <ConfirmDialog
        open={deleteOpen}
        title="Delete version"
        description={
          <>
            This removes {label} of {packageId}. Other versions stay. Jobs
            already uploaded are not deleted. If this is the last version, the
            package leaves the catalog until you publish again.
          </>
        }
        confirmLabel="Delete"
        busy={busy}
        onCancel={() => {
          if (!busy) {
            setDeleteOpen(false);
          }
        }}
        onConfirm={() => void remove()}
      />

      {releaseOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink/40"
          role="dialog"
          aria-modal="true"
          aria-labelledby="release-draft-title"
          onClick={(e) => {
            if (e.target === e.currentTarget && !busy) setReleaseOpen(false);
          }}
        >
          <div className="w-full max-w-md rounded-[14px] border border-hairline bg-canvas shadow-[var(--viewer-shadow-pop)] p-5 space-y-4">
            <div>
              <h2
                id="release-draft-title"
                className="text-lg font-semibold tracking-tight text-ink"
              >
                Release draft
              </h2>
              <p className="text-sm text-mute mt-1">
                Promote the current draft slot to a numbered release. Leave
                version empty to take it from the package archive.
              </p>
            </div>
            <div>
              <label
                htmlFor="release-version"
                className="text-sm font-medium text-ink"
              >
                Version
              </label>
              <Input
                id="release-version"
                value={releaseVersion}
                onChange={(e) => setReleaseVersion(e.target.value)}
                placeholder="from archive"
                disabled={busy}
                className="mt-1.5 text-sm"
              />
            </div>
            <div>
              <p className="text-sm font-medium text-ink">
                Visibility
              </p>
              <Select
                value={releaseVisibility}
                onValueChange={(value) => {
                  if (value === "public" || value === "private") {
                    setReleaseVisibility(value);
                  }
                }}
                disabled={busy}
              >
                <SelectTrigger className="mt-1.5 h-9 min-w-0 w-full text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="private">private</SelectItem>
                  <SelectItem value="public">public</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <label className="flex items-center gap-2 text-sm text-body">
              <input
                type="checkbox"
                checked={replace}
                disabled={busy}
                onChange={(e) => setReplace(e.target.checked)}
              />
              Replace if this version already exists
            </label>
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => setReleaseOpen(false)}
              >
                Cancel
              </Button>
              <Button
                type="button"
                disabled={busy}
                onClick={() => void promote()}
              >
                {busy ? "Releasing…" : "Release"}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
