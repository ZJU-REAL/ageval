/** Leading YAML frontmatter (`---` … `---`) used by SKILL.md and similar. */

const FENCE = /^---[ \t]*\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/;

export type FrontmatterField = { key: string; value: string };

export function splitMarkdownFrontmatter(source: string): {
  fields: FrontmatterField[];
  body: string;
} {
  const match = source.match(FENCE);
  if (!match) return { fields: [], body: source };
  return {
    fields: parseSimpleYamlFields(match[1]),
    body: source.slice(match[0].length),
  };
}

function parseSimpleYamlFields(block: string): FrontmatterField[] {
  const fields: FrontmatterField[] = [];
  let current: FrontmatterField | null = null;
  for (const raw of block.split(/\r?\n/)) {
    const line = raw.replace(/\t/g, "  ");
    const kv = line.match(/^([A-Za-z_][\w.-]*)\s*:\s*(.*)$/);
    if (kv) {
      current = { key: kv[1], value: unquote(kv[2].trim()) };
      fields.push(current);
      continue;
    }
    if (current && /^\s+\S/.test(line)) {
      const extra = line.trim().replace(/^-\s+/, "");
      current.value = current.value ? `${current.value}\n${extra}` : extra;
    }
  }
  return fields;
}

function unquote(value: string): string {
  if (
    (value.startsWith('"') && value.endsWith('"')) ||
    (value.startsWith("'") && value.endsWith("'"))
  ) {
    return value.slice(1, -1);
  }
  return value;
}

export function isMarkdownPath(path: string | null | undefined): boolean {
  const name = (path || "").split("/").pop() || "";
  return /\.(md|markdown|mdx)$/i.test(name);
}
