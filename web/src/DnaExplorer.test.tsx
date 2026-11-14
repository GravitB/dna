import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
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
    fireEvent.click(screen.getByRole("button", { name: "Explore your DNA" }));
    await screen.findByText("Encoded strand #1");
  }
  it("uses saved FASTA, skips unavailable locations, and navigates real strands", async () => {
    await open();
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
  it("sends the exact selected sequence only to the local viewer after its handshake", async () => {
    await open();
    const frame = screen.getByTitle(
      "3D DNA viewer powered by oxView",
    ) as HTMLIFrameElement;
    const spy = vi.spyOn(frame.contentWindow!, "postMessage");
    act(() =>
      window.dispatchEvent(
        new MessageEvent("message", {
          origin: location.origin,
          source: frame.contentWindow,
          data: { type: "lazarus-oxview-ready" },
        }),
      ),
    );
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        expect.objectContaining({
          type: "lazarus-oxview-set",
          sequence: "ACGT",
          duplex: true,
          start: 0,
          length: 4,
        }),
        location.origin,
      ),
    );
    fireEvent.click(
      screen.getByLabelText(
        "Show a generated complementary strand to illustrate a double helix",
      ),
    );
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        expect.objectContaining({
          type: "lazarus-oxview-set",
          sequence: "ACGT",
          duplex: false,
          start: 0,
          length: 4,
        }),
        location.origin,
      ),
    );
  });
  it("does not trust viewer acknowledgements from another origin", async () => {
    await open();
    const frame = screen.getByTitle(
      "3D DNA viewer powered by oxView",
    ) as HTMLIFrameElement;
    act(() =>
      window.dispatchEvent(
        new MessageEvent("message", {
          origin: "https://other.example",
          source: frame.contentWindow,
          data: { type: "lazarus-oxview-ready" },
        }),
      ),
    );
    expect(
      (
        screen.getByRole("button", {
          name: "Build strand visually",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });
  it("ignores stale render confirmations after changing the model", async () => {
    await open();
    const frame = screen.getByTitle(
      "3D DNA viewer powered by oxView",
    ) as HTMLIFrameElement;
    const spy = vi.spyOn(frame.contentWindow!, "postMessage");
    const receive = (data: Record<string, unknown>) =>
      act(() =>
        window.dispatchEvent(
          new MessageEvent("message", {
            origin: location.origin,
            source: frame.contentWindow,
            data,
          }),
        ),
      );
    receive({ type: "lazarus-oxview-ready" });
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const original = spy.mock.calls.find(
      ([data]) => data.type === "lazarus-oxview-set",
    )![0];
    const confirmation = {
      type: "lazarus-oxview-rendered",
      sequence: "ACGT",
      renderedSequence: "ACGT",
      start: 0,
      requestId: original.requestId,
    };
    receive(confirmation);
    expect(
      screen.getByText("3D model matches these saved DNA bases."),
    ).toBeTruthy();
    fireEvent.click(
      screen.getByLabelText(
        "Show a generated complementary strand to illustrate a double helix",
      ),
    );
    receive(confirmation);
    expect(
      screen.queryByText("3D model matches these saved DNA bases."),
    ).toBeNull();
    const requests = spy.mock.calls.filter(
      ([data]) => data.type === "lazarus-oxview-set",
    );
    const latest = requests[requests.length - 1][0];
    receive({ ...confirmation, requestId: latest.requestId });
    expect(
      screen.getByText("3D model matches these saved DNA bases."),
    ).toBeTruthy();
  });
  it("shows loading failures with retry and never creates a placeholder helix", async () => {
    vi.mocked(fetch).mockResolvedValue({ ok: false } as Response);
    render(<DnaExplorer job={job} />);
    fireEvent.click(screen.getByRole("button", { name: "Explore your DNA" }));
    await screen.findByRole("alert");
    expect(
      screen.getByRole("button", { name: "Try loading DNA again" }),
    ).toBeTruthy();
    expect(screen.queryByTitle("3D DNA viewer powered by oxView")).toBeNull();
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
