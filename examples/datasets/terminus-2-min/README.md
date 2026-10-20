# terminus-2-min

One docker task. The agent writes `hello.txt` from a tmux pane. PASS comes from `evaluator.py`.

Install the plugin, then point `OPENAI_API_KEY` and `OPENAI_BASE_URL` at a chat-completions endpoint:

```bash
ageval plugin install plugins/terminus-2
ageval lock examples/datasets/terminus-2-min --task hello
ageval run examples/datasets/terminus-2-min --task hello
```

The attempt image needs a package manager when tmux is not already in the image layer. The evaluator host does not need tmux or a Harbor install.
