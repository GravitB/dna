import { useEffect, useState } from "react";
import { api, date } from "./api";
import type { Archive } from "./types";

// ---------------------------------------------------------------- browser-held org credentials

export type SavedOrg = { id: string; name: string; token: string };
const KEY = "lazarus-orgs";

export function savedOrgs(): SavedOrg[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}
export function saveOrg(o: SavedOrg) {
  try {
    localStorage.setItem(KEY, JSON.stringify([o, ...savedOrgs().filter((x) => x.id !== o.id)]));
  } catch {
    /* storage unavailable: the token is still shown once to copy */
  }
}
export function forgetOrg(id: string) {
  try {
    localStorage.setItem(KEY, JSON.stringify(savedOrgs().filter((x) => x.id !== id)));
  } catch {
    /* ignore */
  }
}
export function orgHeaders(orgId?: string | null): Record<string, string> {
  const o = orgId ? savedOrgs().find((x) => x.id === orgId) : null;
  return o ? { "X-Lazarus-Org-Token": o.token } : {};
}

async function send(path: string, init: RequestInit, orgId?: string | null) {
  const r = await fetch(`/api${path}`, {
    ...init,
    headers: { ...(init.headers as Record<string, string>), ...orgHeaders(orgId) },
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(typeof d.detail === "string" ? d.detail : "Request failed. Please try again.");
  }
  return r;
}
const json = (body: object) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
function filenameOf(r: Response, fallback: string) {
  const m = /filename\*=UTF-8''([^;]+)/.exec(r.headers.get("content-disposition") || "");
  return m ? decodeURIComponent(m[1]) : fallback;
}
async function saveResponse(r: Response, fallback: string) {
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filenameOf(r, fallback);
  a.click();
  URL.revokeObjectURL(url);
}

type Org = {
  id: string;
  name: string;
  created: string;
  current_version: number;
  versions: { version: number; fingerprint: string; created: string; status: string }[];
  backups: { exported: string; versions: number[] }[];
  backup_current: boolean;
  archives: string[];
};

// ---------------------------------------------------------------- organization page

export function OrgPage() {
  const [orgs, setOrgs] = useState(savedOrgs);
  const [current, setCurrent] = useState(orgs[0]?.id || "");
  const [name, setName] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = () => setOrgs(savedOrgs());

  async function create() {
    setBusy(true);
    setError("");
    try {
      const r = await (await send("/orgs", json({ name }))).json();
      saveOrg({ id: r.org.id, name: r.org.name, token: r.access_token });
      setToken(r.access_token);
      setName("");
      refresh();
      setCurrent(r.org.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="idx">One key · every archive</p>
          <h1>Organization keys</h1>
          <p>
            One master key per organization protects the unique data keys of all its archives.
            Recovery needs only your exported backup, each archive’s Recovery Package and the DNA.
          </p>
        </div>
      </div>
      {error && <div className="error" role="alert">{error}</div>}
      {token && (
        <div className="info" role="status">
          <b>Access token, shown once:</b> <code className="mono">{token}</code>
          <br />
          It is saved in this browser and authorizes key operations for this organization. Copy it
          somewhere safe. Next: export a master key backup below.
          <div>
            <button className="small-button" onClick={() => setToken("")}>I have saved it</button>
          </div>
        </div>
      )}
      <div className="archive-layout">
        <section className="form-panel">
          {orgs.length > 0 && (
            <label>
              Organization
              <select value={current} onChange={(e) => setCurrent(e.target.value)}>
                {orgs.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name} · {o.id}
                  </option>
                ))}
              </select>
            </label>
          )}
          {current ? <OrgDetail key={current} id={current} onForget={() => { forgetOrg(current); refresh(); setCurrent(savedOrgs()[0]?.id || ""); }} /> : (
            <p className="muted">No organization in this browser yet. Create one, or restore from a backup.</p>
          )}
        </section>
        <aside>
          <h2>New organization</h2>
          <label>
            Name
            <input value={name} placeholder="e.g. Mercy General Hospital" onChange={(e) => setName(e.target.value)} />
          </label>
          <button className="primary" disabled={busy || !name.trim()} onClick={create}>
            Create organization and master key
          </button>
          <Restore onRestored={(o) => { refresh(); setCurrent(o); }} />
        </aside>
      </div>
    </>
  );
}

function OrgDetail({ id, onForget }: { id: string; onForget: () => void }) {
  const [org, setOrg] = useState<Org | null>(null);
  const [error, setError] = useState("");
  const load = () =>
    send(`/orgs/${id}`, {}, id)
      .then((r) => r.json())
      .then(setOrg)
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, [id]);
  if (error)
    return (
      <div className="error">
        {error}
        <div>
          <button className="small-button" onClick={onForget}>Remove from this browser</button>
        </div>
      </div>
    );
  if (!org) return <p role="status">Loading…</p>;
  const cur = org.versions.find((v) => v.version === org.current_version);
  return (
    <>
      <h2>{org.name}</h2>
      <dl className="summary">
        <div>
          <dt>Master key</dt>
          <dd>Version {org.current_version}</dd>
        </div>
        <div>
          <dt>Backup of current version</dt>
          <dd className={org.backup_current ? "success-text" : "failure-text"}>
            {org.backup_current ? "Exported" : "Not exported"}
          </dd>
        </div>
        <div>
          <dt>Archives protected</dt>
          <dd>{org.archives.length}</dd>
        </div>
        <div>
          <dt>Created</dt>
          <dd>{date(org.created)}</dd>
        </div>
      </dl>
      <p className="fine">
        Fingerprint of version {org.current_version}: <span className="hash">{cur?.fingerprint}</span> (identifies
        the key without revealing it). Raw keys are never shown.
      </p>
      {!org.backup_current && (
        <div className="error">
          Export a backup now. Archives can be protected by this key only after a backup of the current
          version exists. If every copy of the backup and its passphrase is lost, archives protected by this
          key cannot be recovered by anyone.
        </div>
      )}
      <Backup id={id} onDone={load} />
      <Rotate id={id} version={org.current_version} onDone={load} />
      <Migrate id={id} onDone={load} />
      {org.versions.length > 1 && (
        <details>
          <summary>Key versions</summary>
          <ul>
            {org.versions.map((v) => (
              <li key={v.version}>
                v{v.version} · {v.status} · <span className="hash">{v.fingerprint}</span> · {date(v.created)}
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}

function Backup({ id, onDone }: { id: string; onDone: () => void }) {
  const [p1, setP1] = useState("");
  const [p2, setP2] = useState("");
  const [ack, setAck] = useState(false);
  const [scope, setScope] = useState("all");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  async function go() {
    setBusy(true);
    setMsg("");
    try {
      const r = await send(`/orgs/${id}/master-key/backup`, json({ passphrase: p1, confirm_passphrase: p2, acknowledge: ack, scope }), id);
      await saveResponse(r, `${id}-master-key.json`);
      setP1("");
      setP2("");
      setMsg("Backup downloaded. Store copies offline in separate places, and keep the passphrase apart from them.");
      onDone();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="dna-step" open>
      <summary>Back up the master key</summary>
      <p>
        The backup is the master key encrypted with your passphrase (scrypt + AES-256-GCM). It is the
        only way the key leaves Lazarus, and with each archive’s Recovery Package it is all you need to
        recover, even if Lazarus no longer exists.
      </p>
      <label>
        Passphrase (12+ characters; a few unrelated words work well)
        <input type="password" autoComplete="new-password" value={p1} onChange={(e) => setP1(e.target.value)} />
      </label>
      <label>
        Repeat passphrase
        <input type="password" autoComplete="new-password" value={p2} onChange={(e) => setP2(e.target.value)} />
      </label>
      <fieldset className="mode">
        <legend>Include</legend>
        <label className="inline">
          <input type="radio" checked={scope === "all"} onChange={() => setScope("all")} /> All key versions (opens older Recovery Packages too)
        </label>
        <label className="inline">
          <input type="radio" checked={scope === "current"} onChange={() => setScope("current")} /> Current version only
        </label>
      </fieldset>
      <label className="inline">
        <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I understand that
        losing every copy of this backup or its passphrase can make our archives permanently unrecoverable.
      </label>
      <button disabled={busy || p1.length < 12 || p1 !== p2 || !ack} onClick={go}>
        {busy ? "Encrypting…" : "Download master key backup"}
      </button>
      {msg && <p role="status">{msg}</p>}
    </details>
  );
}

function Rotate({ id, version, onDone }: { id: string; version: number; onDone: () => void }) {
  const [confirm, setConfirm] = useState(false);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  async function go() {
    setBusy(true);
    setMsg("");
    try {
      const r = await (await send(`/orgs/${id}/master-key/rotate`, json({ confirm }), id)).json();
      setMsg(`Now on version ${r.to_version}. ${r.archives_rewrapped.length} archive(s) re-wrapped, ${r.recovery_packages_reissued} Recovery Package(s) re-issued. ${r.note}`);
      setConfirm(false);
      onDone();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="dna-step">
      <summary>Rotate the master key</summary>
      <p>
        Creates version {version + 1} and re-wraps every archive’s data keys under it. The DNA is not
        re-synthesized. Recovery Packages issued before the rotation keep needing a backup that holds
        version {version}; download the re-issued packages and export a new backup afterwards.
      </p>
      <label className="inline">
        <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} /> Rotate to version {version + 1}
      </label>
      <button disabled={busy || !confirm} onClick={go}>{busy ? "Re-wrapping…" : "Rotate master key"}</button>
      {msg && <p role="status">{msg}</p>}
    </details>
  );
}

function Migrate({ id, onDone }: { id: string; onDone: () => void }) {
  const [list, setList] = useState<{ id: string; name: string; created: string }[] | null>(null);
  const [archive, setArchive] = useState("");
  const [del, setDel] = useState(false);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () =>
    send(`/orgs/${id}/legacy-archives`, {}, id)
      .then((r) => r.json())
      .then((l) => {
        setList(l);
        setArchive(l[0]?.id || "");
      })
      .catch((e) => setMsg(e.message));
  async function go() {
    setBusy(true);
    setMsg("");
    try {
      const r = await (await send(`/orgs/${id}/migrate`, json({ archive_id: archive, delete_legacy_keys: del }), id)).json();
      setMsg(`Migrated and verified (${r.verification}). Recovery Package revision ${r.recovery_package_revision} issued. ${r.note}`);
      onDone();
      load();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="dna-step" onToggle={(e) => (e.currentTarget as HTMLDetailsElement).open && !list && load()}>
      <summary>Bring older archives under this key</summary>
      <p>
        Wraps an existing archive’s per-file keys under this organization’s master key, then proves it
        by decoding the archive’s DNA with the wrapped keys. Only after that check passes is anything
        switched. Legacy key files are kept unless you choose otherwise.
      </p>
      {list && !list.length && <p className="muted">No legacy archives on this server.</p>}
      {!!list?.length && (
        <>
          <label>
            Archive
            <select value={archive} onChange={(e) => setArchive(e.target.value)}>
              {list.map((a) => (
                <option key={a.id} value={a.id}>{a.name} · {a.id}</option>
              ))}
            </select>
          </label>
          <label className="inline">
            <input type="checkbox" checked={del} onChange={(e) => setDel(e.target.checked)} /> Delete the legacy
            key files after the verified migration
          </label>
          <button disabled={busy || !archive} onClick={go}>{busy ? "Migrating and verifying…" : "Migrate archive"}</button>
        </>
      )}
      {msg && <p role="status">{msg}</p>}
    </details>
  );
}

function Restore({ onRestored }: { onRestored: (id: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [pass, setPass] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  async function go() {
    if (!file) return;
    setBusy(true);
    setMsg("");
    const fd = new FormData();
    fd.append("backup_file", file);
    fd.append("passphrase", pass);
    try {
      const r = await (await send("/orgs/restore", { method: "POST", body: fd })).json();
      if (r.access_token) saveOrg({ id: r.org.id, name: r.org.name, token: r.access_token });
      setPass("");
      setMsg(r.restored
        ? `Organization restored on this server (versions ${r.verified_versions.join(", ")}). A new access token was saved in this browser.`
        : `Backup verified: versions ${r.verified_versions.join(", ")} match this organization’s keys.`);
      onRestored(r.org.id);
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="dna-step">
      <summary>Verify or restore a backup</summary>
      <p className="muted small">
        Checks a backup against this server, or re-establishes the organization from it on a new server.
      </p>
      <label className="upload">
        Master key backup
        <input type="file" accept=".json,application/json" onChange={(e) => setFile(e.target.files?.[0] || null)} />
      </label>
      <label>
        Passphrase
        <input type="password" autoComplete="off" value={pass} onChange={(e) => setPass(e.target.value)} />
      </label>
      <button disabled={busy || !file || !pass} onClick={go}>{busy ? "Checking…" : "Verify or restore"}</button>
      {msg && <p role="status">{msg}</p>}
    </details>
  );
}

// ---------------------------------------------------------------- archive: long-term recovery

export function LongTermRecovery({ job, onChange }: { job: Archive; onChange?: () => void }) {
  const orgId = job.key_management?.mode === "organization" ? job.key_management.org_id : job.org_id;
  const rp = job.recovery_package;
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [reqs, setReqs] = useState<string | null>(null);
  const noToken = !!orgId && !savedOrgs().some((o) => o.id === orgId);
  async function step(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setMsg("");
    try {
      await fn();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  const create = () =>
    step("create", async () => {
      const r = await (await send(`/jobs/${job.id}/recovery-package`, { method: "POST" }, orgId)).json();
      setMsg(`Recovery Package revision ${r.revision} created.`);
      onChange?.();
    });
  const download = () =>
    step("download", async () => {
      await saveResponse(await send(`/jobs/${job.id}/recovery-package`, {}, orgId), "lazarus-recovery-package-v1.zip");
    });
  const requirements = () =>
    step("reqs", async () => {
      setReqs(reqs === null ? await (await send(`/jobs/${job.id}/synthesis-requirements`, {})).text() : null);
    });
  const test = (source: string) =>
    step("test", async () => {
      const s = await (await send(`/jobs/${job.id}/recovery-package/test`, json({ source }), orgId)).json();
      location.hash = `#/decoder?session=${s.id}`;
    });
  const hasSim = (job.simulations || []).some((s) => s.status === "complete");
  return (
    <section className="long-term">
      <div className="section-heading">
        <h2>Long-term recovery</h2>
        <span className="badge">
          {orgId ? `Organization key v${job.key_management?.kek_version ?? "?"}` : "Legacy key file"}
        </span>
      </div>
      <p className="muted">
        The clean FASTA is what a synthesis provider would manufacture. The Recovery Package is what
        someone needs decades from now, with your key and the sequencing reads, to rebuild these files
        without Lazarus.
      </p>
      {noToken && (
        <div className="info">This archive belongs to an organization whose access token is not in this browser. Restore its backup on the Organization keys page to download key material.</div>
      )}
      <div className="actions">
        <a className="button" href={`/api/jobs/${job.id}/files/exports/pre_simulation.fasta?download=1`}>
          Download Clean FASTA
        </a>
        {rp ? (
          <button className="primary" disabled={!!busy || noToken} onClick={download}>
            Download Recovery Package
          </button>
        ) : (
          <button className="primary" disabled={!!busy || noToken} onClick={create}>
            {busy === "create" ? "Building package…" : "Create Long-Term Recovery Package"}
          </button>
        )}
        <button disabled={!!busy || !rp} onClick={requirements} aria-expanded={reqs !== null}>
          View Synthesis Requirements
        </button>
        <button disabled={!!busy || !rp || noToken} onClick={() => test(hasSim ? "simulation" : "clean")}>
          {busy === "test" ? "Starting…" : "Test Independent Recovery"}
        </button>
      </div>
      {rp && (
        <p className="fine">
          Revision {rp.revision} · {date(rp.created)} · SHA-256 <span className="hash">{rp.sha256}</span>
          {rp.encryption?.kek_version != null && ` · wrapped under master key v${rp.encryption.kek_version}`}
          {" · "}
          <button className="link-button" disabled={!!busy || noToken} onClick={create}>Re-issue</button>
          <br />
          Test Independent Recovery decodes {hasSim ? "the latest simulated reads" : "the clean design"} using only
          the package’s metadata and wrapped keys. Simulated evidence, not a laboratory result.
        </p>
      )}
      {reqs !== null && <pre className="requirements">{reqs}</pre>}
      {msg && <p role="status">{msg}</p>}
    </section>
  );
}

// ---------------------------------------------------------------- new archive: choose organization

export function OrgChoice({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  const orgs = savedOrgs();
  return (
    <label>
      Key protection
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Per-archive key file (legacy)</option>
        {orgs.map((o) => (
          <option key={o.id} value={o.id}>
            {o.name}: organization master key
          </option>
        ))}
      </select>
      <small>
        {orgs.length
          ? "Organization archives get their own data keys, wrapped by your organization’s master key."
          : <>Set up an organization on the <a href="#/organization">Organization keys</a> page to protect every archive with one master key.</>}
      </small>
    </label>
  );
}
