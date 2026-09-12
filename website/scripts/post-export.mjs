import { copyFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * GitHub Pages extras after `next build` (`output: "export"`).
 * Relative `en/` works with or without `basePath`.
 */
const out = join(dirname(fileURLToPath(import.meta.url)), "..", "out");

writeFileSync(join(out, ".nojekyll"), "");
copyFileSync(join(out, "api/search"), join(out, "search-index.json"));

writeFileSync(
  join(out, "index.html"),
  `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta http-equiv="refresh" content="0; url=en/" />
    <link rel="canonical" href="en/" />
    <title>ageval</title>
    <script>
      location.replace("en/" + location.search + location.hash);
    </script>
  </head>
  <body>
    <p><a href="en/">ageval</a></p>
  </body>
</html>
`,
);
