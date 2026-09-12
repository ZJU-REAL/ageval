# website/ — reader-facing docs (Fumadocs)

This tree does not own mechanism or product spec. On conflict, change `docs/` / `ARCHITECTURE.md` first, then this tree.

**Terms:** before you write or edit copy here, read [`docs/glossary.md`](../docs/glossary.md). Use only the canonical names. Do not invent a new word on the page. Unknown concept → add it to the glossary first.

`website/` is a **public** surface. Public pages may use only glossary rows marked public or both. Internal words on a public page are a defect. After edits, run `python3 scripts/check_public_terms.py`.

Readers: people who install the CLI, run a dataset, or author one. Not contributors. Mark contributor-only sections as such.

## Do not index the docs in the body

The sidebar and `content/docs/index.mdx` (`index.zh-CN.mdx`) are the catalog. Do not build a second one in the prose.

Do not:

- Send the reader away with “see [Hub](/docs/share/hub)” (or the Chinese “见 [Hub]”)
- End a page with “Next: A · B · C” / “下一步：A · B · C” listing sibling pages
- Substitute a `/docs/...` link for finishing the fact on this page

Write what this page owes. If the fact belongs on another path, the sidebar takes them there.

Exception: `index.mdx` / `index.zh-CN.mdx` may carry a site map.

When that catalog (or a necessary in-page cross-ref) must link, use a **relative MDX path** (`./getting-started/install.mdx`, `../reference/cli.mdx`). Absolute `/docs/...` drops the locale prefix and 404s. `createRelativeLink` only resolves `./` and `../`.

Off-site links (ACP, e2b, GitHub tree paths) are fine. No GitHub Issue numbers.

## Reader and placement (docs-substance)

Name who is reading and what they can do after. A word stays only if that reader would still know it without this repo.

| Layer | Where it goes |
| --- | --- |
| Floor (any eval product already has this) | Not a feature. Not the lead of a section |
| Basic (install, run, fields) | Body, commands, tables |
| Beyond peers (cheaper / reusable in a way they are not) | Feature block only |

Plugin, scoring, and `lock` are usually basic. Do not sell an implementation filename.

## Voice

Match the pages already here: command first, short sentences, tables for parallel facts. Keep product names as in the glossary (`dataset`, Hub, PASS, CLI, `profiles.yaml`). Chinese and English are separate pages. Do not mix.

Hygiene (`docs-substance` + `humanizer-zh`):

- Say who does what. Drop “furthermore”, “crucial”, “not only… but…”, “a testament to…”
- No punch lines. Do not split a point into three for symmetry
- Em dashes are not rhythm. Bold only a product name or a CLI flag
- Do not cycle synonyms for a glossary term. English pages stay English
- No chat filler (“hope this helps”) and no knowledge-cutoff disclaimers
- Trust the reader: missing credentials → lock/run does not start. Do not soften it

Read it aloud. Break a run of three same-length sentences.

Chinese public copy follows glossary principle 2: **一次运行** / **整份 dataset 跑完**. Do not teach Attempt or suite as Chinese body words. Say **环境**, not box. `profiles.yaml` is the 配置文件 / profiles. “锁定” only for `ageval lock`.

## Bilingual

An English page change needs the matching `*.zh-CN.mdx`. Same slug, same facts, natural phrasing per language — not a mirror translation.

## Check

```sh
python3 scripts/check_public_terms.py
pnpm --dir website lint
pnpm --dir website build
```
