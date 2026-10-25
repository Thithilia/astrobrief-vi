import { defineCollection } from 'astro:content';
import { z } from 'astro/zod';
import { glob } from 'astro/loaders';

const dateString = z.preprocess(
  (value) => value instanceof Date ? value.toISOString().slice(0, 10) : value,
  z.string(),
);

const summaries = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './content/summaries' }),
  schema: z.object({
    id: z.string().optional(),
    doi: z.string().min(1),
    title: z.string().min(1),
    dek: z.string().default(''),
    journal: z.string().min(1),
    paper_title: z.string().default(''),
    authors: z.array(z.string()).default([]),
    summary_date: dateString,
    generated_at: z.string().optional(),
    published_online: dateString.nullish(),
    online_date_precision: z.string().nullish(),
    issue_date: dateString.nullish(),
    first_seen: z.string().nullish(),
    topic: z.string().default('other'),
    reading_minutes: z.coerce.number().positive().default(6),
    byline: z.string().default('Tổng hợp tự động bằng Codex'),
    source: z.looseObject({
      kind: z.string().default('publisher'),
      url: z.url(),
      version: z.string().nullish(),
      license: z.string().nullish(),
    }),
    figures: z.array(z.looseObject({
      src: z.string(),
      alt: z.string().default('Hình minh họa từ bài nghiên cứu'),
      caption: z.string().default(''),
      credit: z.string().default(''),
      license: z.string().default(''),
      original_url: z.string().default(''),
      source_locator: z.string().default(''),
    })).default([]),
    glossary: z.array(z.object({ vi: z.string(), en: z.string() })).default([]),
    references: z.array(z.object({ label: z.string(), url: z.string() })).default([]),
  }).catchall(z.unknown()),
});

export const collections = { summaries };
