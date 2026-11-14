import type { Comparison, Trial } from "./LearnedArchive";
export type Policy = {
  retention_years: number;
  budget_usd: number;
  tech: string;
  coverage: number;
  n_vaults: number;
  target: number;
  notes: string;
};
export type FileInfo = { name: string; bytes: number; included?: boolean };
export type Presentation = {
  needs_retest?: boolean;
  phase: string;
  label: string;
  latest_test: string | null;
  restored_count: number | null;
  verified: boolean | null;
  pending_action: string | null;
};
export type ArchiveSummary = {
  id: string;
  name: string;
  company: string;
  created: string;
  retention_years: number;
  file_count: number | null;
  presentation: Presentation;
};
export type Evidence = {
  scenario: string;
  label: string;
  state: string;
  recovered: number | null;
  trials: number | null;
};
export type Pending = {
  tool: string;
  args: Record<string, number | string>;
  summary: {
    correction?: Record<string, unknown> | null;
    correction_summary?: {write_usd?:number; read_usd?:number; evidence?:Evidence[];can_approve?:boolean};
    write_usd?: number;
    read_usd?: number;
    within_budget?: boolean;
    can_approve?: boolean;
    evidence?: Evidence[];
  };
};
export type Drill = {
  tested_at?: string;
  all_verified: boolean;
  error?: string;
  vaults_available: number[];
  n_vaults: number;
  files: {
    name: string;
    sha256_match: boolean;
    sha256?: string;
    error?: string;
  }[];
  pools: Record<string, unknown>;
};
export type Archive = ArchiveSummary & {
  encoding_mode?: "standard" | "evaluated" | "fresh";
  learning_state?: {status: string; message: string};
  candidate_comparison?: Comparison;
  candidates?: Record<string, {validation?: {state: string; passed: boolean; scenarios: Trial[]}}>;
  analysis_preset?: "standard" | "quick_demo";
  originals_available?: boolean;
  dna_summary?: {data_strands:number; manifest_strands:number; data_letters:number; manifest_letters:number; total_letters:number; example:string} | null;
  storage?: { backend: "local" | "supabase"; state: string };
  policy: Policy;
  selected_files?: string[];
  intake_files?: FileInfo[];
  files: FileInfo[];
  sealed: Record<string, unknown>;
  status: string;
  error?: string;
  finished?: boolean;
  mode?: string;
  pending: Pending | null;
  order: {
    settings: { n_vaults: number };
    cost: { write_usd: number };
    order_files: string[];
  } | null;
  certificate?: string;
  drills: Drill[];
  stress: any[];
  experiments: any[];
  vaults: { vault_id: number; status: string }[];
};
export type Ev = {
  seq: number;
  type: string;
  ts: string;
  agent: string;
  data: any;
};
