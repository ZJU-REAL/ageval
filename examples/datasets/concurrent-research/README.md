# concurrent-research

One Attempt. A coordinator opens six child sessions on `solver`, each with its own search-and-answer loop, at most four at a time. The evaluator scores the published report. This is an integration smoke, not a benchmark score.

`limits.agent_concurrency` is 4. Omitting it would keep the parent serial. `bounded_gather(limit=4)` is the task's own fan-out and cannot raise the parent ceiling.

```bash
ageval lock examples/datasets/concurrent-research --task fanout
ageval run examples/datasets/concurrent-research --task fanout
```

The run needs `glm_coding_api_key` for the `openai-http` profile. A missing key fails before the attempt starts.
