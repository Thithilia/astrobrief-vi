import fs from 'node:fs';
import path from 'node:path';

export type Journal = {
  id: string; name: string; short: string; status: string;
  last_success?: string | null; last_attempt?: string | null; error?: string | null;
};
export type Paper = {
  id: string; doi: string; title: string; journal: string; authors: string[];
  published_online?: string | null; online_date_precision?: string | null;
  issue_date?: string | null; first_seen?: string | null; volume?: string;
  issue?: string; article_number?: string; source_url: string; kind: string;
  topic: string; has_summary: boolean; summary_id?: string | null;
};
export type SummaryPreview = {
  id: string; doi: string; title: string; dek: string; journal: string;
  paper_title: string; summary_date: string; generated_at?: string;
  topic: string; reading_minutes: number; image?: string;
  source: { kind: string; url: string; version?: string | null };
  search_text?: string;
};
export type Catalog = {
  generated_at?: string | null; timezone: string; journals: Journal[];
  papers: Paper[]; summaries: SummaryPreview[];
};

export const TOPICS: Record<string, string> = {
  stars: 'Sao & môi trường liên sao',
  galaxies: 'Thiên hà & nhân hoạt động',
  planets: 'Hành tinh & ngoại hành tinh',
  cosmology: 'Vũ trụ học',
  compact: 'Thiên thể đặc & năng lượng cao',
  solar: 'Mặt Trời & Hệ Mặt Trời',
  methods: 'Phương pháp & thiết bị',
  other: 'Các chủ đề khác',
};

export const JOURNALS: Journal[] = [
  { id: 'aa', short: 'A&A', name: 'Astronomy & Astrophysics', status: 'pending' },
  { id: 'apj', short: 'ApJ', name: 'The Astrophysical Journal', status: 'pending' },
  { id: 'apjl', short: 'ApJL', name: 'The Astrophysical Journal Letters', status: 'pending' },
  { id: 'apjs', short: 'ApJS', name: 'The Astrophysical Journal Supplement Series', status: 'pending' },
  { id: 'aj', short: 'AJ', name: 'The Astronomical Journal', status: 'pending' },
  { id: 'mnras', short: 'MNRAS', name: 'Monthly Notices of the Royal Astronomical Society', status: 'pending' },
];

export function journalName(id: string): string {
  return JOURNALS.find((journal) => journal.id === id)?.short ?? id;
}

export function topicName(id: string): string {
  return TOPICS[id] ?? TOPICS.other;
}

export function internalUrl(value = ''): string {
  const base = import.meta.env.BASE_URL.replace(/\/$/, '');
  return `${base}/${value.replace(/^\//, '')}`;
}

export function assetUrl(value: string): string {
  if (/^https?:\/\//i.test(value)) return value;
  const base = import.meta.env.BASE_URL.replace(/\/$/, '');
  if (value === base || value.startsWith(`${base}/`)) return value;
  return internalUrl(value);
}

export function externalUrl(value: unknown, fallback = '#'): string {
  if (typeof value !== 'string') return fallback;
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : fallback;
  } catch { return fallback; }
}

export function dateKey(value?: string | null): string {
  if (!value) return '';
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  if (!value.includes('T')) return value;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Ho_Chi_Minh', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(date);
  const part = (name: string) => parts.find((entry) => entry.type === name)?.value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}

export function formatDate(value?: string | null, precision?: string | null): string {
  if (!value) return 'Chưa có ngày';
  if (precision === 'year' || /^\d{4}$/.test(value)) return value.slice(0, 4);
  if (precision === 'month' || /^\d{4}-\d{2}$/.test(value)) {
    return `${value.slice(5, 7)}/${value.slice(0, 4)}`;
  }
  const key = dateKey(value);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(key)) return value;
  return `${key.slice(8, 10)}/${key.slice(5, 7)}/${key.slice(0, 4)}`;
}

export function formatTimestamp(value?: string | null): string {
  if (!value) return 'Chưa cập nhật';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return formatDate(value);
  return new Intl.DateTimeFormat('vi-VN', {
    timeZone: 'Asia/Ho_Chi_Minh', dateStyle: 'short', timeStyle: 'short',
  }).format(date);
}

export function safeJson(value: unknown): string {
  return JSON.stringify(value).replace(/</g, '\\u003c').replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029');
}

export function loadCatalog(): Catalog {
  const filename = path.resolve('public/data/catalog.json');
  if (!fs.existsSync(filename)) {
    return { generated_at: null, timezone: 'Asia/Saigon', journals: JOURNALS, papers: [], summaries: [] };
  }
  let data: Record<string, unknown>;
  try { data = JSON.parse(fs.readFileSync(filename, 'utf-8')); }
  catch { throw new Error('Không đọc được public/data/catalog.json: cần JSON hợp lệ.'); }
  if (!Array.isArray(data.papers) || !Array.isArray(data.summaries)) {
    throw new Error('catalog.json phải có hai danh sách papers và summaries.');
  }
  return {
    generated_at: typeof data.generated_at === 'string' ? data.generated_at : null,
    timezone: typeof data.timezone === 'string' ? data.timezone : 'Asia/Saigon',
    journals: JOURNALS.map((journal) => ({
      ...journal,
      ...(Array.isArray(data.journals) ? data.journals.find((item: Journal) => item.id === journal.id) : {}),
    })),
    papers: data.papers as Paper[],
    summaries: data.summaries as SummaryPreview[],
  };
}
