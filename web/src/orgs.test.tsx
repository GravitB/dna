import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LongTermRecovery, OrgPage, orgHeaders, savedOrgs } from "./orgs";
import type { Archive } from "./types";

const fetchMock = vi.fn();
const response = (data: unknown, status = 200) => ({
  ok: status < 400,
  status,
  headers: new Headers(),
  json: async () => data,
  text: async () => String(data),
  blob: async () => new Blob(["zip"]),
});
const org = {
  id: "org-0123456789ab",
  name: "Mercy General",
  created: "2026-11-14T12:00:00Z",
  current_version: 1,
  versions: [{ version: 1, fingerprint: "f".repeat(32), created: "2026-11-14T12:00:00Z", status: "active" }],
  backups: [],
  backup_current: false,
  archives: [],
};

beforeEach(() => {
  localStorage.clear();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("organization keys", () => {
  it("creates an organization, keeps its token and requires a backup before use", async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/orgs" && init?.method === "POST") return response({ org, access_token: "tok-123" });
      if (url === `/api/orgs/${org.id}`) {
        expect((init?.headers as Record<string, string>)["X-Lazarus-Org-Token"]).toBe("tok-123");
        return response(org);
      }
      return response({});
    });
    render(<OrgPage />);
    fireEvent.change(screen.getByPlaceholderText(/Mercy General Hospital/), { target: { value: "Mercy General" } });
    fireEvent.click(screen.getByRole("button", { name: "Create organization and master key" }));
    expect(await screen.findByText("tok-123")).toBeTruthy();
    expect(savedOrgs()).toEqual([{ id: org.id, name: "Mercy General", token: "tok-123" }]);
    expect(orgHeaders(org.id)).toEqual({ "X-Lazarus-Org-Token": "tok-123" });
    expect(await screen.findByText(/Export a backup now/)).toBeTruthy();
    const download = screen.getByRole("button", { name: "Download master key backup" }) as HTMLButtonElement;
    expect(download.disabled).toBe(true);
    const [p1, p2] = screen.getAllByLabelText(/passphrase/i).filter((e) => e.getAttribute("type") === "password");
    fireEvent.change(p1, { target: { value: "four unrelated words" } });
    fireEvent.change(p2, { target: { value: "four unrelated words" } });
    expect(download.disabled).toBe(true); // still needs the loss acknowledgement
    fireEvent.click(screen.getByLabelText(/permanently unrecoverable/));
    expect(download.disabled).toBe(false);
  });

  it("offers the four long-term recovery actions on an approved archive", async () => {
    localStorage.setItem("lazarus-orgs", JSON.stringify([{ id: org.id, name: org.name, token: "tok-123" }]));
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/jobs/job1/recovery-package" && init?.method === "POST") {
        expect((init.headers as Record<string, string>)["X-Lazarus-Org-Token"]).toBe("tok-123");
        return response({ revision: 1 });
      }
      return response({});
    });
    const job = {
      id: "job1",
      order: { settings: { n_vaults: 3 }, cost: { write_usd: 1 }, order_files: [] },
      key_management: { mode: "organization", org_id: org.id, kek_version: 1 },
      simulations: [],
    } as unknown as Archive;
    const onChange = vi.fn();
    render(<LongTermRecovery job={job} onChange={onChange} />);
    expect(screen.getByRole("link", { name: "Download Clean FASTA" }).getAttribute("href")).toContain(
      "exports/pre_simulation.fasta",
    );
    expect((screen.getByRole("button", { name: "View Synthesis Requirements" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Test Independent Recovery" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Create Long-Term Recovery Package" }));
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    expect(screen.getByText("Recovery Package revision 1 created.")).toBeTruthy();
  });
});
