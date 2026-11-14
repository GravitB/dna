import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";
import { DnaExperiment } from "./DnaWorkflow";

const fetchMock = vi.fn();
const response = (data: unknown, status = 200) => ({
  ok: status < 400,
  status,
  json: async () => data,
});
const sim = {
  id: "sim-1",
  created: "2026-11-14T12:00:00Z",
  status: "complete",
  settings: {
    tech: "nanopore", channel: "a", coverage: 10, storage_years: 50, seed: 42, lost_vaults: [],
    sub_rate: null, ins_rate: null, del_rate: null, dropout_rate: null, decay_per_year: null,
  },
  files: {
    "post_simulation_reads.fasta": { path: "simulations/sim-1/post_simulation_reads.fasta", sha256: "ab".repeat(32), bytes: 9000 },
    "simulation_metadata.json": { path: "simulations/sim-1/simulation_metadata.json", sha256: "cd".repeat(32), bytes: 900 },
    "ground_truth.tsv": { path: "simulations/sim-1/ground_truth.tsv", sha256: "ef".repeat(32), bytes: 900 },
  },
  metrics: {
    clean_sequences: 1200, surviving_sequences: 1080, missing_sequences: 120, missing_from_lost_vaults: 0,
    observed_dropout_rate: 0.1, logical_strands: 600, logical_strands_missing: 60, reads: 10800,
    duplicate_reads_kept: 12, mean_reads_per_surviving_sequence: 10, exact_reads: 4000,
    malformed_or_chimeric_reads: 0, observed_error_counts: {},
    observed_error_rates_per_base: { substitution: 0.017, insertion: 0.019, deletion: 0.019, total: 0.055 },
    per_sample_reads: {},
  },
  error: null,
};
const dna = {
  archive_id: "job1",
  notice: "Digital DNA sequences designed by the encoder. They have not been physically synthesized, stored or sequenced.",
  export: {
    created: "2026-11-14T12:00:00Z",
    files: { "exports/pre_simulation.fasta": { sha256: "12".repeat(32), bytes: 150000 } },
    counts: {
      sequences: 1200, per_vault: { "1": 400 }, data_strands: 600, manifest_strands_per_vault: 200,
      n_vaults: 3, strand_lengths: [110], total_nucleotides: 132000, redundancy: 1, gc_mean: 0.5,
    },
    encoder_configuration: { approved_settings: {}, pools: { "pool-0000": { settings: {}, n_bytes: 1, n_chunks: 300 } } },
  },
  order_settings: {},
  vault_files: [],
  simulations: [sim],
  decodes: [{ id: "dec-1", created: "x", verdict: "PASS", simulation_id: "sim-1", files_verified: 1, files: 1 }],
};
const session = {
  id: "dec-20261114-120000-abcdef",
  created: "2026-11-14T12:00:00Z",
  status: "complete",
  mode: "existing_archive",
  archive_id: "job1",
  simulation_id: "sim-1",
  fasta_name: "post_simulation_reads.fasta",
  decoders: ["baseline", "polish"],
  steps: [{ step: "files", status: "done", detail: "1 of 1 files verified" }],
  verdict: "PASS",
  error: null,
  files: [{ index: 0, name: "image.png", bytes: 10, sha256: "99".repeat(32) }],
  summary: {
    verdict: "PASS",
    verdict_text: "All expected file hashes match.",
    missing: [],
    warnings: [],
    manifest_source: "dna",
    seconds: 3.2,
    files: [{ name: "image.png", verified: true, status: "verified", reason: null, expected_sha256: "99".repeat(32), actual_sha256: "99".repeat(32), decoder: "baseline" }],
    decoders: {
      baseline: { verdict: "PASS", seconds: 1, pools_recovered: 1, pools: 1, manifest_recovered: true },
      polish: { verdict: "PASS", seconds: 2, pools_recovered: 1, pools: 1, manifest_recovered: true },
    },
    input: { filename: "post_simulation_reads.fasta", format: "fasta", records: 10800, sha256: "ab", samples: {} },
    simulation_id: "sim-1",
  },
};

beforeEach(() => {
  location.hash = "#/";
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === "/api/health") return response({ llm: false });
    if (path === "/api/jobs/job1/dna") return response(dna);
    if (path === "/api/decoder/capabilities")
      return response({
        decoders: { baseline: { available: true, label: "" }, polish: { available: true, label: "" } },
        archives: [{ id: "job1", name: "Trial", simulations: [{ id: "sim-1", created: "x", seed: 42 }] }],
      });
    if (path === "/api/decoder/sessions" && init?.method === "POST") return response({ ...session, status: "queued", summary: undefined }, 202);
    if (path === "/api/decoder/sessions") return response([]);
    if (path.startsWith("/api/decoder/sessions/")) return response(session);
    return response({});
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("DNA experiment workflow", () => {
  it("shows clean and damaged DNA steps with adjacent downloads and honest labels", async () => {
    const job: any = { order: { settings: { n_vaults: 3 }, order_files: [] }, policy: { tech: "nanopore", coverage: 10, retention_years: 50 } };
    render(<DnaExperiment id="job1" job={job} />);
    await screen.findByText("Step 1 — Original Encoded DNA (Pre-Simulation)");
    expect(screen.getByText("Step 2 — Damaged DNA (Post-Simulation)")).toBeTruthy();
    expect(screen.getByText(/not been physically synthesized/)).toBeTruthy();
    expect(screen.getByText(/not laboratory results/)).toBeTruthy();
    const pre = screen.getAllByRole("link", { name: "Download Pre-Simulation FASTA" });
    const post = screen.getByRole("link", { name: "Download Post-Simulation FASTA" });
    expect(pre[pre.length - 1].getAttribute("href")).toBe("/api/jobs/job1/files/exports/pre_simulation.fasta?download=1");
    expect(post.getAttribute("href")).toBe("/api/jobs/job1/files/simulations/sim-1/post_simulation_reads.fasta?download=1");
    // pre and post download buttons are siblings in the results view
    expect(pre[pre.length - 1].parentElement).toBe(post.parentElement);
    expect(screen.getByRole("link", { name: "Download All Clean DNA Files" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Inspect DNA Sequences" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Download Simulation Metadata" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Compare Before vs. After" })).toBeTruthy();
    expect(screen.getByText("1,080")).toBeTruthy(); // surviving sequences
    expect(screen.getByRole("link", { name: "Decode this FASTA in the DNA Decoder" }).getAttribute("href")).toBe(
      "#/decoder?archive=job1&simulation=sim-1",
    );
  });

  it("runs the standalone decoder on a simulation and shows hash verification", async () => {
    location.hash = "#/decoder?archive=job1&simulation=sim-1";
    render(<App />);
    expect((await screen.findAllByText("DNA Decoder")).length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.getByRole("option", { name: /sim-1 · seed 42/ })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Run Decoding" }));
    await screen.findByText(/All expected file hashes match/);
    const call = fetchMock.mock.calls.find(([p, o]) => p === "/api/decoder/sessions" && o?.method === "POST")!;
    const fd = call[1].body as FormData;
    expect(fd.get("mode")).toBe("existing_archive");
    expect(fd.get("source")).toBe("simulation");
    expect(fd.get("simulation_id")).toBe("sim-1");
    expect(fd.get("decoders")).toBe("both");
    expect(fd.get("fasta_file")).toBeNull();
    expect(screen.getByText("Byte-exact (baseline)")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Download verified file" }).getAttribute("href")).toBe(
      `/api/decoder/sessions/${session.id}/files/recovered/0?download=1`,
    );
    expect(screen.getByText("CNN PolishDecoder")).toBeTruthy();
  });

  it("requires a FASTA for independent import and never offers downloads for failed files", async () => {
    location.hash = "#/decoder";
    const failed = {
      ...session,
      verdict: "FAIL",
      files: [],
      summary: {
        ...session.summary,
        verdict: "FAIL",
        verdict_text: "No file was recovered with a matching hash.",
        files: [{ ...session.summary.files[0], verified: false, status: "dna_failed", reason: "pool(s) not recovered from DNA: pool-0000", actual_sha256: null }],
      },
    };
    fetchMock.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/api/health") return response({ llm: false });
      if (path === "/api/decoder/capabilities")
        return response({ decoders: { baseline: { available: true, label: "" }, polish: { available: false, reason: "no checkpoint", label: "" } }, archives: [] });
      if (path === "/api/decoder/sessions" && init?.method === "POST") return response(failed, 202);
      if (path === "/api/decoder/sessions") return response([]);
      if (path.startsWith("/api/decoder/sessions/")) return response(failed);
      return response({});
    });
    render(<App />);
    fireEvent.click(await screen.findByLabelText(/B — Independent import/));
    fireEvent.click(screen.getByRole("button", { name: "Run Decoding" }));
    await screen.findByText("Choose a FASTA or FASTQ file to decode.");
    const input = screen.getByLabelText(/FASTA or FASTQ reads/) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File([">r sample=MANIFEST\nACGT\n"], "reads.fasta")] } });
    fireEvent.click(screen.getByRole("button", { name: "Run Decoding" }));
    await screen.findByText(/No file was recovered with a matching hash/);
    expect(screen.getByText("pool(s) not recovered from DNA: pool-0000")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Download verified file" })).toBeNull();
    expect((screen.getByRole("option", { name: /CNN PolishDecoder/ }) as HTMLOptionElement).disabled).toBe(true);
  });
});
