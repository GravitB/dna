export type DnaStrand = {
  header: string;
  pool: string;
  index: number;
  sequence: string;
};
/** FASTA remains the source of truth; never substitute a decorative/demo sequence. */
export function parseDnaFasta(text: string): DnaStrand[] {
  const records: DnaStrand[] = [];
  const seen = new Set<string>();
  let header = "";
  let parts: string[] = [];
  function finish() {
    if (!header) return;
    const match = /^([^|]+)\|(\d+)$/.exec(header);
    const sequence = parts.join("").toUpperCase();
    if (
      !match ||
      !Number.isSafeInteger(Number(match[2])) ||
      !sequence ||
      sequence.length > 1000 ||
      !/^[ACGT]+$/.test(sequence) ||
      seen.has(header)
    )
      throw new Error("The saved DNA file has an invalid or duplicate strand.");
    seen.add(header);
    records.push({ header, pool: match[1], index: Number(match[2]), sequence });
  }
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    if (line.startsWith(">")) {
      finish();
      header = line.slice(1);
      parts = [];
    } else {
      if (!header) throw new Error("The saved DNA file is not valid FASTA.");
      parts.push(line);
    }
  }
  finish();
  if (!records.length)
    throw new Error("No DNA strands were found at this location.");
  return records;
}
export function complement(sequence: string) {
  return [...sequence]
    .map((base) => ({ A: "T", T: "A", C: "G", G: "C" })[base] || "")
    .join("");
}

export type Mark = { index: number; kind: "sub" | "del" | "ins" };

/** Turn an alignment (clean vs read) into per-position damage marks on the clean strand. */
export function marksFromSegments(segments: { op: string; clean: string; read: string }[]): Mark[] {
  const out: Mark[] = [];
  let c = 0;
  for (const s of segments) {
    if (s.op === "equal") c += s.clean.length;
    else if (s.op === "replace") {
      for (let k = 0; k < s.clean.length; k++) out.push({ index: c + k, kind: "sub" });
      c += s.clean.length;
    } else if (s.op === "delete") {
      for (let k = 0; k < s.clean.length; k++) out.push({ index: c + k, kind: "del" });
      c += s.clean.length;
    } else out.push({ index: c, kind: "ins" });
  }
  return out;
}
