import { defineCollection } from 'astro:content';
import { z } from 'astro/zod';
import { glob } from 'astro/loaders';

const guides = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/guides', generateId: ({ entry }) => entry.replace(/\.md$/, '') }),
  schema: z.object({
    title: z.string(), description: z.string(),
    locale: z.enum(['zh', 'en']), slug: z.string(),
    sources: z.array(z.string()).min(1),
  }),
});
export const collections = { guides };
