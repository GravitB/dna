import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import App from "./App";
const fetchMock = vi.fn();
const response = (data: unknown, status = 200) => ({
  ok: status < 400,
  status,
  json: async () => data,
});
const sample = [
  { name: "final.txt", bytes: 20 },
  { name: "draft.txt", bytes: 10 },
];
const job = {
  id: "test",
  name: "Trial records",
  company: "Example",
  created: "2026-11-14T12:00:00Z",
  policy: { retention_years: 50, budget_usd: 50, n_vaults: 3, target: 1 },
  presentation: { phase: "review", label: "Review proposal" },
  selected_files: ["final.txt"],
  intake_files: [{ name: "final.txt", bytes: 20, included: true }],
  files: [],
  sealed: { "final.txt": {} },
  stress: [],
  experiments: [],
  drills: [],
  vaults: [],
  pending: {
    tool: "place_synthesis_order",
    args: { n_vaults: 3 },
    summary: {
      can_approve: false,
      evidence: [
        {
          scenario: "vault_loss",
          label: "Loss of one location",
          state: "missing",
          trials: null,
        },
      ],
    },
  },
};
beforeEach(() => {
  sessionStorage.clear();
  location.hash = "#/";
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === "/api/jobs" && init?.method === "POST")
      return response({ job_id: "test" });
    if (path === "/api/health") return response({ llm: false });
    if (path === "/api/jobs") return response([]);
    if (path === "/api/samples") return response(sample);
    if (path.endsWith("/eventlog")) return response([]);
    if (path === "/api/jobs/test") return response(job);
    return response({});
  });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal(
    "EventSource",
    class {
      onmessage = null;
      close() {}
    },
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
describe("business archive workspace", () => {
  it("explains simulation and separates sample archives from personal uploads", async () => {
    render(<App />);
    await screen.findByText("Your first archive starts with your records.");
    expect(screen.getByText("Simulation workspace")).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Try a picture demo" })
        .getAttribute("href"),
    ).toBe("#/new?sample");
    expect(screen.queryByText("ANTHROPIC_API_KEY")).toBeNull();
  });
  it("preserves records and requirements through the wizard and submits explicit selection", async () => {
    location.hash = "#/new";
    render(<App />);
    fireEvent.change(screen.getByLabelText(/Choose records/), {target:{files:[new File(["final"],"final.txt"),new File(["draft"],"draft.txt")]}});
    await screen.findByText("final.txt");
    fireEvent.click(screen.getByLabelText(/draft.txt/));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.change(screen.getByLabelText(/How many years should we simulate\?/), {
      target: { value: "25" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(
      (screen.getByLabelText(/draft.txt/) as HTMLInputElement).checked,
    ).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(
      (screen.getByLabelText(/How many years should we simulate\?/) as HTMLInputElement)
        .value,
    ).toBe("25");
    fireEvent.change(screen.getByLabelText("Encoding approach"), {target:{value:"standard"}});
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Analyze archive" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([p, o]) => p === "/api/jobs" && o?.method === "POST",
        ),
      ).toBe(true),
    );
    const fd = fetchMock.mock.calls.find(
      ([p, o]) => p === "/api/jobs" && o?.method === "POST",
    )![1].body as FormData;
    expect(JSON.parse(fd.get("selected_files") as string)).toEqual([
      "final.txt",
    ]);
    expect(JSON.parse(fd.get("policy") as string).retention_years).toBe(25);
    expect(fd.get("encoding_mode")).toBe("standard");
  });
  it("blocks approval without matching passing evidence", async () => {
    location.hash = "#/job/test";
    render(<App />);
    const approve = await screen.findByRole("button", {
      name: "Approve simulated archive",
    });
    expect((approve as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Not tested for this design")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Reject proposal" }),
    ).toBeTruthy();
  });
  it("shows per-file outcomes and asks for confirmation before simulating location loss", async () => {
    location.hash = "#/job/test";
    fetchMock.mockImplementation(async (path: string) => {
      if (path === "/api/health") return response({ llm: false });
      if (path.endsWith("/eventlog")) return response([]);
      if (path === "/api/jobs/test")
        return response({
          ...job,
          pending: null,
          finished: true,
          status: "certified",
          presentation: {
            phase: "results",
            label: "Recovery verified",
            verified: true,
          },
          certificate: "certificate.html",
          order: {
            settings: { n_vaults: 3 },
            cost: { write_usd: 46 },
            order_files: [],
          },
          vaults: [{ vault_id: 1, status: "healthy" }],
          drills: [
            {
              tested_at: "2026-11-14T12:00:00Z",
              all_verified: true,
              vaults_available: [1, 2, 3],
              n_vaults: 3,
              files: [{ name: "final.txt", sha256_match: true }],
            },
          ],
        });
      return response({});
    });
    render(<App />);
    await screen.findByText("All selected files restored unchanged");
    expect(
      screen.getByRole("link", { name: "Open restored file" }),
    ).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Simulate loss of location" }),
    );
    expect(screen.getByText("Simulate loss of location 1?")).toBeTruthy();
    expect(fetchMock.mock.calls.some(([p]) => p.includes("/destroy"))).toBe(
      false,
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(
      screen.queryByRole("button", { name: "Confirm simulated loss" }),
    ).toBeNull();
  });
  it("shows recoverable service errors", async () => {
    fetchMock.mockImplementation(async () => {
      throw new Error("offline");
    });
    render(<App />);
    await screen.findByText("Cannot connect to the archive service.");
    expect(
      screen.getAllByRole("button", { name: "Try again" }).length,
    ).toBeGreaterThan(0);
  });
});
