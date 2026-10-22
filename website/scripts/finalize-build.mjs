import { writeFile, rm, readFile } from "node:fs/promises";
import { loadEnv } from "vite";
import { siteMetadata, locales, guideSlugs } from "../src/lib/site.ts";
import { strictPagefindChunks } from './strict-pagefind.mjs';

const entry = JSON.parse(await readFile('dist/pagefind/pagefind-entry.json', 'utf8'));
if (entry.version !== '1.5.2') throw new Error('Review Pagefind strict chunk handling after upgrading.');
for (const file of ['pagefind.js', 'pagefind-worker.js']) {
  const path = `dist/pagefind/${file}`;
  await writeFile(path, strictPagefindChunks(await readFile(path, 'utf8')));
}

const env = loadEnv("production", process.cwd(), "PUBLIC_");
const meta = siteMetadata(
  process.env.PUBLIC_SITE_URL || env.PUBLIC_SITE_URL,
  "/zh/",
);
if (meta.indexable) {
  const paths = locales.flatMap((locale) => [
    `/${locale}/`,
    ...guideSlugs.map((slug) => `/${locale}/docs/${slug}/`),
  ]);
  const escape = (value) =>
    value
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll('"', "&quot;");
  await writeFile(
    "dist/sitemap.xml",
    `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${paths.map((path) => `<url><loc>${escape(meta.origin + path)}</loc></url>`).join("")}</urlset>\n`,
  );
  await writeFile(
    "dist/robots.txt",
    `User-agent: *\nAllow: /\nDisallow: /pagefind/\nSitemap: ${meta.origin}/sitemap.xml\n`,
  );
} else {
  await rm("dist/sitemap.xml", { force: true });
  await writeFile("dist/robots.txt", "User-agent: *\nDisallow: /\n");
}
console.log(
  `Metadata: ${meta.indexable ? meta.origin : "private preview · noindex · no sitemap"}`,
);
