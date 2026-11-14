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
export type SimSettings = {
  tech: string;
  channel: string;
  coverage: number;
  storage_years: number;
  seed: number;
  lost_vaults: number[];
  sub_rate: number | null;
  ins_rate: number | null;
  del_rate: number | null;
  dropout_rate: number | null;
  decay_per_year: number | null;
};
export type SimMetrics = {
  clean_sequences: number;
  surviving_sequences: number;
  missing_sequences: number;
  missing_from_lost_vaults: number;
  observed_dropout_rate: number;
  logical_strands: number;
  logical_strands_missing: number;
  reads: number;
  duplicate_reads_kept: number;
  mean_reads_per_surviving_sequence: number;
  exact_reads: number;
  malformed_or_chimeric_reads: number;
  observed_error_counts: Record<string, number>;
  observed_error_rates_per_base: {
    substitution: number;
    insertion: number;
    deletion: number;
    total: number;
  };
  per_sample_reads: Record<string, number>;
};
export type ArtifactRef = { path: string; sha256: string; bytes: number };
export type Simulation = {
  id: string;
  created: string;
  status: "running" | "complete" | "failed";
  settings: SimSettings;
  files: Record<string, ArtifactRef>;
  metrics: SimMetrics | null;
  profile?: Record<string, unknown>;
  error: string | null;
  seconds?: number;
};
export type DecodeSummary = {
  id: string;
  created: string;
  verdict: Verdict;
  simulation_id: string | null;
  files_verified: number;
  files: number;
};
export type Verdict = "PASS" | "PARTIAL" | "FAIL" | "INCOMPLETE";
export type DnaExport = {
  archive_id: string;
  notice: string;
  export: {
    created: string;
    files: Record<string, { sha256: string; bytes: number }>;
    counts: {
      sequences: number;
      per_vault: Record<string, number>;
      data_strands: number;
      manifest_strands_per_vault: number;
      n_vaults: number;
      strand_lengths: number[];
      total_nucleotides: number;
      redundancy: number;
      gc_mean: number | null;
    };
    encoder_configuration: {
      approved_settings: Record<string, unknown>;
      pools: Record<string, { settings: Record<string, unknown>; n_bytes: number; n_chunks: number }>;
    };
  };
  order_settings: Record<string, unknown>;
  vault_files: string[];
  simulations: Simulation[];
  decodes: DecodeSummary[];
};
export type Segment = { op: string; clean: string; read: string };
export type CompareStrand = {
  id: string;
  clean: string;
  missing: boolean;
  reads_total: number;
  reads: {
    read_id: string;
    sequence: string;
    edit_distance: number;
    substitutions: number;
    insertions: number;
    deletions: number;
    malformed: boolean;
    segments: Segment[];
  }[];
};
export type DecodeFile = {
  name: string;
  verified: boolean;
  status: string;
  reason: string | null;
  expected_sha256: string;
  actual_sha256?: string | null;
  expected_bytes?: number;
  decoder?: string | null;
};
export type DecodeSession = {
  id: string;
  created: string;
  status: "queued" | "running" | "complete" | "failed";
  mode: string;
  archive_id: string | null;
  simulation_id: string | null;
  fasta_name: string;
  decoders: string[];
  steps: { step: string; status: string; detail: string }[];
  verdict: Verdict | null;
  error: string | null;
  storage_error?: string;
  files: { index: number; name: string; bytes: number; sha256: string }[];
  summary?: {
    verdict: Verdict;
    verdict_text: string;
    missing: string[];
    warnings: string[];
    manifest_source: string | null;
    seconds: number;
    files: DecodeFile[];
    decoders: Record<
      string,
      {
        available?: boolean;
        reason?: string;
        verdict?: Verdict;
        seconds?: number;
        pools_recovered?: number;
        pools?: number;
        manifest_recovered?: boolean;
      }
    >;
    input: { filename: string; format: string; records: number; sha256: string; samples: Record<string, number> };
    simulation_id: string | null;
  };
};
