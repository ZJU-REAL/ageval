# harbor-hello

One Harbor task. The oracle writes `hello.txt`. `tests/test.sh` scores that file.

```bash
ageval run examples/datasets/harbor-hello --layout harbor --oracle
```

`--oracle` runs `solution/solve.sh` and does not call the agent. Omit `--oracle` to send `instruction.md` once to role `solver`. That role id is fixed. Bind it from `profiles.yaml`, `--profiles`, or `--agent` (`solver` or `*`). `--task` is not used: this directory is the task.
