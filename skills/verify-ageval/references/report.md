# How to report a verify-ageval run

Write one line per check. Use these words only:

| Result | When |
| --- | --- |
| `passed` | The command ran and the assertion held |
| `failed` | The command ran and the assertion did not hold |
| `not run` | The command did not run, or a skip flag / missing credential stopped it |

`AGEVAL_SKIP_REAL_ACP=1` means the real ACP path is **not run**. Do not call that path passed.

A loopback `openai-http` PASS does not cover ACP, docker, e2b, ssh, or daytona. Name the path that passed.

Missing `E2B_API_KEY`, an SSH locator, or an ACP entry binary: that check is **not run**. `--probe` that exits not-ready is a failed probe only when the credentials were present. When they were absent, write **not run**.

Keep the evidence directory. Delete only the gateway process you started and the temporary `AGEVAL_HOME`.
