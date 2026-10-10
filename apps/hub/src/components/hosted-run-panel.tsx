import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { FieldLabel } from "@/components/field-label";
import { suiteDetailPath } from "@/components/suite-inspector";
import { SignInLink } from "@/components/sign-in-button";
import { Button } from "@ageval/shared/components/ui/button";
import { Input } from "@ageval/shared/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@ageval/shared/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@ageval/shared/components/ui/table";
import { INTERNAL_LINK_CLASS } from "@ageval/shared/lib/links";
import { formatDay } from "@ageval/shared/lib/utils";
import {
  cancelHostedJob,
  createHostedJob,
  listHostedJobs,
  listOrgSecrets,
  listOrgs,
  RegistryHttpError,
  type HostedJob,
  type OrgRow,
  type OrgSecret,
} from "@/lib/api";
import { getToken } from "@/lib/auth";
import { toastError } from "@/lib/toast-error";

const DATASET_PROFILES = "dataset-profiles";

const AGENT_OPTIONS = [
  { id: DATASET_PROFILES, label: "Dataset profiles" },
  { id: "pi", label: "Pi" },
  { id: "opencode", label: "OpenCode" },
  { id: "codex", label: "Codex" },
  { id: "claude-code", label: "Claude Code" },
  { id: "grok-build", label: "Grok Build" },
  { id: "openai-http", label: "OpenAI HTTP" },
  { id: "anthropic-http", label: "Anthropic HTTP" },
] as const;

function errorText(err: unknown): string {
  if (err instanceof RegistryHttpError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

function liveJob(job: HostedJob): boolean {
  return job.status === "queued" || job.status === "running";
}

export function HostedRunPanel({
  datasetId,
  version,
  releaseOrgId,
}: {
  datasetId: string;
  version: string;
  releaseOrgId?: string | null;
}) {
  const token = getToken();
  const [orgs, setOrgs] = useState<OrgRow[]>([]);
  const [orgId, setOrgId] = useState("");
  const [secrets, setSecrets] = useState<OrgSecret[]>([]);
  const [jobs, setJobs] = useState<HostedJob[]>([]);
  const [environment, setEnvironment] = useState<"e2b" | "daytona">("e2b");
  const [agentRef, setAgentRef] = useState<string>(DATASET_PROFILES);
  const [model, setModel] = useState("");
  const [modelSecretId, setModelSecretId] = useState("");
  const [providerSecretId, setProviderSecretId] = useState("");
  const [concurrency, setConcurrency] = useState("1");
  const [taskId, setTaskId] = useState("");
  const [busy, setBusy] = useState(false);
  const [canceling, setCanceling] = useState<string | null>(null);
  const listError = useRef<string | null>(null);

  const memberOrgs = useMemo(
    () => orgs.filter((org) => Boolean(org.role)),
    [orgs],
  );
  const modelSecrets = useMemo(
    () => secrets.filter((row) => row.kind === "model"),
    [secrets],
  );
  const providerSecrets = useMemo(
    () =>
      secrets.filter(
        (row) => row.kind === "provider" && row.provider === environment,
      ),
    [secrets, environment],
  );

  const loadJobs = useCallback(async () => {
    if (!token) return;
    try {
      const rows = await listHostedJobs(token, { datasetId });
      setJobs(rows);
      listError.current = null;
    } catch (err) {
      const message = errorText(err);
      if (listError.current !== message) {
        listError.current = message;
        toastError(err);
      }
    }
  }, [datasetId, token]);

  useEffect(() => {
    void loadJobs();
  }, [loadJobs]);

  const polling = jobs.some(liveJob);
  useEffect(() => {
    if (!token || !polling) return;
    const timer = window.setInterval(() => {
      void loadJobs();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [loadJobs, polling, token]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    listOrgs(token)
      .then((rows) => {
        if (cancelled) return;
        setOrgs(rows);
        setOrgId((current) => {
          if (current && rows.some((org) => org.org_id === current && org.role)) {
            return current;
          }
          const preferred = releaseOrgId
            ? rows.find((org) => org.org_id === releaseOrgId && org.role)
            : undefined;
          return preferred?.org_id || rows.find((org) => org.role)?.org_id || "";
        });
      })
      .catch((err: unknown) => {
        if (!cancelled) toastError(err);
      });
    return () => {
      cancelled = true;
    };
  }, [releaseOrgId, token]);

  useEffect(() => {
    if (!token || !orgId) {
      setSecrets([]);
      return;
    }
    let cancelled = false;
    listOrgSecrets(orgId, token)
      .then((rows) => {
        if (!cancelled) setSecrets(rows);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setSecrets([]);
          toastError(err);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [orgId, token]);

  useEffect(() => {
    if (modelSecretId && !modelSecrets.some((row) => row.secret_id === modelSecretId)) {
      setModelSecretId("");
    }
  }, [modelSecretId, modelSecrets]);

  useEffect(() => {
    if (
      providerSecretId &&
      !providerSecrets.some((row) => row.secret_id === providerSecretId)
    ) {
      setProviderSecretId("");
    }
  }, [providerSecretId, providerSecrets]);

  if (!token) {
    return (
      <p className="text-sm text-body">
        <SignInLink /> to submit a hosted job. v1 runs on e2b or daytona.
      </p>
    );
  }

  async function submit() {
    const modelId = model.trim();
    const tasks = Number(concurrency);
    if (!orgId || !modelId || !modelSecretId || !providerSecretId) {
      toastError(new Error("Choose an organization, model, and both secrets"));
      return;
    }
    if (!Number.isInteger(tasks) || tasks < 1 || tasks > 32) {
      toastError(new Error("Concurrency is a whole number from 1 to 32"));
      return;
    }
    const task = taskId.trim();
    setBusy(true);
    try {
      const created = await createHostedJob(
        {
          org_id: orgId,
          dataset_id: datasetId,
          version,
          environment,
          model: modelId,
          model_secret_id: modelSecretId,
          provider_secret_id: providerSecretId,
          max_concurrent_tasks: tasks,
          ...(agentRef !== DATASET_PROFILES ? { agent_ref: agentRef } : {}),
          ...(task ? { task_id: task } : {}),
        },
        token,
      );
      setJobs((rows) => [created, ...rows.filter((row) => row.job_id !== created.job_id)]);
    } catch (err) {
      toastError(err);
    } finally {
      setBusy(false);
    }
  }

  async function cancel(jobId: string) {
    setCanceling(jobId);
    try {
      const next = await cancelHostedJob(jobId, token);
      setJobs((rows) => rows.map((row) => (row.job_id === jobId ? next : row)));
    } catch (err) {
      toastError(err);
    } finally {
      setCanceling(null);
    }
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <p className="text-sm text-body">
        Queue this version on e2b or daytona. The worker in this deployment
        runs the suite and uploads it. Model and provider keys come from{" "}
        {orgId ? (
          <Link
            to={`/organizations/${encodeURIComponent(orgId)}?tab=secrets`}
            className={INTERNAL_LINK_CLASS}
          >
            org secrets
          </Link>
        ) : (
          "org secrets"
        )}
        . Secret values are not shown again after you save them.
      </p>

      {memberOrgs.length === 0 ? (
        <p className="text-sm text-mute">
          Join an organization before submitting a hosted job.
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <FieldLabel>Organization</FieldLabel>
            <Select value={orgId || undefined} onValueChange={setOrgId}>
              <SelectTrigger className="mt-1.5 h-9 min-w-0 w-full text-sm" aria-label="Organization">
                <SelectValue placeholder="Organization" />
              </SelectTrigger>
              <SelectContent>
                {memberOrgs.map((org) => (
                  <SelectItem key={org.org_id} value={org.org_id}>
                    {org.display_name || org.name || org.org_id}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <FieldLabel>Environment</FieldLabel>
            <Select
              value={environment}
              onValueChange={(next) => {
                if (next === "e2b" || next === "daytona") setEnvironment(next);
              }}
            >
              <SelectTrigger className="mt-1.5 h-9 min-w-0 w-full text-sm" aria-label="Environment">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="e2b">e2b</SelectItem>
                <SelectItem value="daytona">daytona</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <FieldLabel>Agent</FieldLabel>
            <Select value={agentRef} onValueChange={setAgentRef}>
              <SelectTrigger className="mt-1.5 h-9 min-w-0 w-full text-sm" aria-label="Agent">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {AGENT_OPTIONS.map((agent) => (
                  <SelectItem key={agent.id} value={agent.id}>
                    {agent.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <FieldLabel htmlFor="hosted-model">Model</FieldLabel>
            <Input
              id="hosted-model"
              value={model}
              onChange={(event) => setModel(event.target.value)}
              placeholder="gpt-4.1"
              className="mt-1.5 text-sm"
            />
          </div>
          <div>
            <FieldLabel>Model secret</FieldLabel>
            <Select
              value={modelSecretId || undefined}
              onValueChange={setModelSecretId}
              disabled={modelSecrets.length === 0}
            >
              <SelectTrigger className="mt-1.5 h-9 min-w-0 w-full text-sm" aria-label="Model secret">
                <SelectValue placeholder={modelSecrets.length ? "Model secret" : "No model secrets"} />
              </SelectTrigger>
              <SelectContent>
                {modelSecrets.map((row) => (
                  <SelectItem key={row.secret_id} value={row.secret_id}>
                    {row.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <FieldLabel>Provider secret</FieldLabel>
            <Select
              value={providerSecretId || undefined}
              onValueChange={setProviderSecretId}
              disabled={providerSecrets.length === 0}
            >
              <SelectTrigger className="mt-1.5 h-9 min-w-0 w-full text-sm" aria-label="Provider secret">
                <SelectValue
                  placeholder={
                    providerSecrets.length ? "Provider secret" : `No ${environment} secrets`
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {providerSecrets.map((row) => (
                  <SelectItem key={row.secret_id} value={row.secret_id}>
                    {row.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <FieldLabel htmlFor="hosted-concurrency">Concurrency</FieldLabel>
            <Input
              id="hosted-concurrency"
              type="number"
              min={1}
              max={32}
              value={concurrency}
              onChange={(event) => setConcurrency(event.target.value)}
              className="mt-1.5 text-sm"
            />
          </div>
          <div>
            <FieldLabel htmlFor="hosted-task">Task</FieldLabel>
            <Input
              id="hosted-task"
              value={taskId}
              onChange={(event) => setTaskId(event.target.value)}
              placeholder="Whole suite"
              className="mt-1.5 text-sm"
            />
          </div>
          <div className="sm:col-span-2">
            <Button type="button" disabled={busy} onClick={() => void submit()}>
              {busy ? "Submitting…" : "Submit hosted job"}
            </Button>
          </div>
        </div>
      )}

      {jobs.length === 0 ? (
        <p className="text-sm text-mute">No hosted jobs for this dataset.</p>
      ) : (
        <div className="blob-panel overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Status</TableHead>
                <TableHead>Environment</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Version</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Suite</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {jobs.map((job) => (
                <TableRow key={job.job_id}>
                  <TableCell>
                    <div>{job.status}</div>
                    {job.error?.message ? (
                      <div className="text-error">{job.error.message}</div>
                    ) : null}
                    {liveJob(job) ? (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="mt-1"
                        disabled={canceling === job.job_id}
                        onClick={() => void cancel(job.job_id)}
                      >
                        Cancel
                      </Button>
                    ) : null}
                  </TableCell>
                  <TableCell>{job.environment}</TableCell>
                  <TableCell>{job.model}</TableCell>
                  <TableCell>{job.version}</TableCell>
                  <TableCell className="text-mute">{formatDay(job.created_at)}</TableCell>
                  <TableCell>
                    {job.suite_run_id ? (
                      <Link
                        to={suiteDetailPath(datasetId, job.suite_run_id)}
                        className={INTERNAL_LINK_CLASS}
                      >
                        {job.suite_run_id}
                      </Link>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
