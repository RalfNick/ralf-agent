import { defineConfig } from 'astro/config';
import { loadEnv } from 'vite';
import { repositoryLinks } from './src/lib/repository.mjs';
import { satteri } from '@astrojs/markdown-satteri';

const env = loadEnv(process.env.NODE_ENV ?? 'production', process.cwd(), 'PUBLIC_');
const site = process.env.PUBLIC_SITE_URL || env.PUBLIC_SITE_URL || undefined;

export default defineConfig({
  site,
  output: 'static',
  trailingSlash: 'always',
  devToolbar: { enabled: false },
  markdown: { processor: satteri({ mdastPlugins: [repositoryLinks] }), shikiConfig: { theme: 'github-dark' } },
  vite: { server: { fs: { strict: true } } },
});
