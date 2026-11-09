export type DocStatus = 'queued' | 'reading' | 'masking' | 'extracting' | 'ready' | 'failed';
export type DocType = 'rent_agreement' | 'electricity_bill' | 'bank_statement' | 'property_record' | 'other';
export type Confidence = 'high' | 'medium' | 'low' | 'missing';

export interface User {
  id: string;
  name: string;
  email: string;
  is_demo: boolean;
}

export interface Session {
  token: string;
  user: User;
}

export interface DocSummary {
  id: string;
  filename: string;
  status: DocStatus;
  error: string | null;
  doc_type: DocType | null;
  language: string;
  page_count: number | null;
  pii_counts: Record<string, number>;
  text_source: 'pdf_text' | 'ocr' | 'demo_prepared' | null;
  original_deleted: boolean;
  is_demo: boolean;
  created_at: string;
  updated_at: string;
}

export interface Field {
  name: string;
  label_en: string;
  label_hi: string;
  value: string | number | null;
  page: number | null;
  confidence: Confidence;
}

export interface DocDetail extends DocSummary {
  meta: {
    summary: string;
    language: string;
    classification_confidence: string;
    provider: string;
    model: string;
    demo_mode: boolean;
  } | null;
  fields: Field[];
}

export interface QaItem {
  id?: number;
  question: string;
  answer: string;
  language: string;
  citations: number[];
  refused: boolean;
  sources?: { page: number; text: string }[];
  demo_mode?: boolean;
  pending?: boolean;
}

export interface Meta {
  provider: string;
  model: string;
  demo_mode: boolean;
  ocr_enabled: boolean;
  voice_enabled: boolean;
  limits: { max_upload_mb: number; max_pages: number };
}

export const IN_PROGRESS: DocStatus[] = ['queued', 'reading', 'masking', 'extracting'];
