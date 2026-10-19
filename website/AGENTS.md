# website/ — reader-facing docs (Fumadocs)

This tree provides reader-facing documentation and does not own mechanism or product specifications (`docs/` and `ARCHITECTURE.md` hold authority when specifications conflict). When wrapping up user-visible changes, update the corresponding pages in this tree.

**Terminology:** Before writing or editing copy here, read [`docs/glossary.md`](../docs/glossary.md). Use canonical names and avoid internal slang. After edits, run `python3 scripts/check_public_terms.py`.

Target readers: developers and researchers who install the CLI, run a dataset, or author tasks and plugins. Mark contributor-only sections explicitly.

## Do not duplicate the sidebar catalog in page body

The sidebar and `content/docs/index.mdx` (`index.zh-CN.mdx`) serve as the catalog. Avoid building a second navigation index at the bottom of content pages.

- Do not end pages with a "Next: A · B · C" link list.
- State the facts that belong to the current page directly.
- When an in-page cross-reference is needed, use a **relative MDX path** (`./getting-started/install.mdx`, `../reference/cli.mdx`). Absolute `/docs/...` paths drop the locale prefix and 404 (`createRelativeLink` resolves `./` and `../` only).
- External links (ACP, E2B, GitHub source paths) are allowed. Do not include GitHub Issue numbers (`#60`, `Issue #59`).

## Writing style

- Lead with the problem or command, use concise sentences, and use tables for structured comparisons or field definitions.
- Keep canonical terms consistent (`dataset`, `task`, `Attempt`, `suite`, `profiles.yaml`, `PASS` / `FAIL` / `ERROR`, `ModelSpec`).
- Keep English and Simplified Chinese on their respective `.mdx` and `.zh-CN.mdx` pages with matching slugs and facts.
- Avoid bureaucratic jargon ("抓手", "赋能", "透传") and overused contrast frames ("不是 X，而是 Y").

## Verification

```sh
python3 scripts/check_public_terms.py
pnpm --dir website lint
pnpm --dir website build
```

Website, Hub, and Viewer UIs are verified on the rendered page. Do not add component, snapshot, or copy-grep test files under `apps/` or `website/`.
