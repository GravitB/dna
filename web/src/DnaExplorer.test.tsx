import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
vi.mock("./Helix3D", () => ({
  default: (p: { sequence: string | null; duplex?: boolean; selected?: number | null; onSelect?: (i: number) => void }) => (
    <div
      data-testid="helix"
      data-sequence={p.sequence ?? ""}
      data-duplex={String(p.duplex)}
      data-selected={p.selected ?? ""}
    >
      <button data-testid="pick-0" onClick={() => p.onSelect?.(0)} />
    </div>
  ),
}));
import DnaExplorer from "./DnaExplorer";
import { parseDnaFasta, complement } from "./dna";
import type { Archive } from "./types";
const fasta =
  ">MANIFEST|0\nAAAA\n>pool-0000|0\nACGT\n>pool-0000|2\nTGCA\n>pool-0001|1\nGGCC\n";
const job = {
  id: "archive-one",
  order: { order_files: [] },
  vaults: [
    { vault_id: 1, status: "healthy" },
    { vault_id: 2, status: "destroyed" },
    { vault_id: 3, status: "healthy" },
  ],
} as unknown as Archive;
beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, text: async () => fasta })),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
describe("DNA parsing", () => {
  it("preserves actual sequences, indices and manifest separation", () => {
    const strands = parseDnaFasta(">pool-0000|2\nac\ngt\n");
    expect(strands).toEqual([
      { header: "pool-0000|2", pool: "pool-0000", index: 2, sequence: "ACGT" },
    ]);
    expect(complement("ACGT")).toBe("TGCA");
  });
  it.each([
    "not fasta",
    ">pool|0\nACNX",
    ">pool|0\nAC\n>pool|0\nGT",
    ">pool|9999999999999999999999\nACGT",
  ])("rejects invalid data instead of displaying fake DNA: %s", (input) => {
    expect(() => parseDnaFasta(input)).toThrow();
  });
});
describe("archive DNA explorer", () => {
  async function open() {
    render(<DnaExplorer job={job} />);
    await screen.findByText("Encoded strand #1");
    await screen.findByTestId("helix");
  }
  const helix = () => screen.getByTestId("helix");
  const ready = () => screen.findByTestId("helix");
  it("opens on approved archives, uses saved FASTA, skips unavailable locations, and navigates real strands", async () => {
    await open();
    expect(screen.queryByRole("button", { name: "Explore your DNA" })).toBeNull();
    expect(fetch).toHaveBeenCalledWith(
      "/api/jobs/archive-one/files/vaults/vault-1/order.fasta",
      expect.anything(),
    );
    expect(screen.queryByRole("option", { name: "Location 2" })).toBeNull();
    expect(screen.getByRole("button", { name: "Base 1: A" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Next DNA strand" }));
    expect(screen.getByText("Encoded strand #3")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Base 1: T" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("DNA group"), {
      target: { value: "MANIFEST" },
    });
    expect(
      screen.getByRole("option", { name: "Archive instructions (manifest)" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Base 1: A" })).toBeTruthy();
  });
  it("renders the exact saved bases in 3D and toggles the generated complement", async () => {
    await open();
    expect(helix().dataset.sequence).toBe("ACGT");
    expect(helix().dataset.duplex).toBe("true");
    fireEvent.click(
      screen.getByLabelText(
        "Show a generated complementary strand to illustrate a double helix",
      ),
    );
    expect(helix().dataset.duplex).toBe("false");
    expect(helix().dataset.sequence).toBe("ACGT");
    fireEvent.click(screen.getByRole("button", { name: "Next DNA strand" }));
    expect(helix().dataset.sequence).toBe("TGCA");
  });
  it("keeps the letter track and the 3D selection in sync", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Base 3: G" }));
    expect(helix().dataset.selected).toBe("2");
    expect(screen.getByRole("button", { name: "Base 3: G" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByTestId("pick-0"));
    expect(screen.getByRole("button", { name: "Base 1: A" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Next DNA strand" }));
    expect(helix().dataset.selected).toBe("");
  });
  it("shows loading failures with retry and never creates a placeholder helix", async () => {
    vi.mocked(fetch).mockResolvedValue({ ok: false } as Response);
    render(<DnaExplorer job={job} />);
    await screen.findByRole("alert");
    expect(
      screen.getByRole("button", { name: "Try loading DNA again" }),
    ).toBeTruthy();
    expect(screen.queryByTestId("helix")).toBeNull();
  });
  it("does not invent sequences before archive approval", () => {
    render(<DnaExplorer job={{ ...job, order: null }} />);
    expect(
      (
        screen.getByRole("button", {
          name: "Explore your DNA",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(fetch).not.toHaveBeenCalled();
  });
});
