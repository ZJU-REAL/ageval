const urls = import.meta.glob("./assets/*.{svg,png}", {
  query: "?url",
  import: "default",
  eager: true,
}) as Record<string, string>;

const byFile = new Map<string, string>();
for (const [path, url] of Object.entries(urls)) {
  const file = path.split("/").pop();
  if (file) byFile.set(file, url);
}

export function catalogAssetUrl(file: string): string | undefined {
  return byFile.get(file);
}
