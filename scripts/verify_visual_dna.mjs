/** Read-only browser check using an existing archive; never approves or deletes data. */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
const require = createRequire(new URL("../web/package.json", import.meta.url));
const { chromium } = require("playwright");
const base = process.env.LAZARUS_TEST_URL || "http://127.0.0.1:8000";
const options = {
  headless: true,
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
};
if (process.env.CHROME_EXECUTABLE)
  options.executablePath = process.env.CHROME_EXECUTABLE;
const browser = await chromium.launch(options);
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const errors = [],
  mutations = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("request", (r) => {
  if (
    r.url().startsWith(base + "/api/") &&
    !["GET", "HEAD"].includes(r.method())
  )
    mutations.push(r.method() + " " + r.url());
});
try {
  let id = process.env.LAZARUS_ARCHIVE_ID;
  if (!id) {
    const r = await page.request.get(base + "/api/jobs");
    assert.ok(r.ok());
    for (const entry of await r.json()) {
      const r = await page.request.get(base + "/api/jobs/" + entry.id);
      assert.ok(r.ok());
      const j = await r.json();
      if (j.order && j.vaults.some((v) => v.status !== "destroyed")) {
        id = j.id;
        break;
      }
    }
  }
  assert.ok(
    id,
    "Create and approve a sample archive before running this read-only viewer check.",
  );
  await page.goto(base + "/#/job/" + id);
  await page.getByRole("button", { name: "Explore your DNA" }).click();
  const ready = () =>
    page
      .getByText("3D model matches these saved DNA bases.")
      .waitFor({ timeout: 30000 });
  const frame = () =>
    page.frames().find((f) => f.url().includes("/oxview/index.html"));
  const sequence = async () =>
    (await page.locator(".dna-letters button").allTextContents()).join("");
  await ready();
  let full = await sequence();
  let actual = await frame().evaluate(() => ({
    sequence: systems[0].strands[0].getSequence(),
    strands: systems[0].strands.length,
    count: elements.size,
    drawCalls: renderer.info.render.calls,
  }));
  assert.equal(actual.sequence, full.slice(0, 30));
  assert.equal(actual.strands, 2);
  assert.ok(actual.drawCalls > 0);
  // Independently verify that the displayed letters came from the committed FASTA.
  const location = await page.getByLabel("Storage location").inputValue();
  const fasta = await page.request.get(
    `${base}/api/jobs/${id}/files/vaults/vault-${location}/order.fasta`,
  );
  assert.ok(fasta.ok());
  const header = (
    await page.locator(".dna-sequence-heading small").textContent()
  )
    .split("·")
    .pop()
    .trim();
  const record = (await fasta.text())
    .split(">")
    .find((r) => r.split(/\r?\n/)[0] === header);
  assert.ok(record);
  assert.equal(full, record.split(/\r?\n/).slice(1).join("").trim());
  console.log("PASS: actual saved FASTA rendered by oxView.");
  const output = fileURLToPath(new URL("../scratch/", import.meta.url));
  await mkdir(output, { recursive: true });
  await page.locator(".dna-explorer").scrollIntoViewIfNeeded();
  await page
    .locator(".dna-explorer")
    .screenshot({ path: output + "visual-dna-desktop.png" });
  await page.getByLabel("3D detail").selectOption("whole");
  await ready();
  assert.equal(
    await frame().evaluate(() => systems[0].strands[0].getSequence()),
    full,
  );
  await page.getByLabel("3D detail").selectOption("close");
  await ready();
  await page
    .getByRole("button", {
      name: `Base ${full.length}: ${full[full.length - 1]}`,
      exact: true,
    })
    .click();
  await ready();
  assert.equal(
    await frame().evaluate(() => systems[0].strands[0].getSequence()),
    full.slice(-30),
  );
  await page.getByRole("button", { name: "Build strand visually" }).click();
  await page.getByText(/Building the visual model:/).waitFor();
  await ready();
  await page
    .getByLabel(
      "Show a generated complementary strand to illustrate a double helix",
    )
    .uncheck();
  await ready();
  assert.equal(await frame().evaluate(() => systems[0].strands.length), 1);
  console.log(
    "PASS: close-up, full sequence, base selection, animation and single-strand mode.",
  );
  const downloaded = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download this strand (FASTA)" })
    .click();
  const stream = await (await downloaded).createReadStream();
  const chunks = [];
  for await (const c of stream) chunks.push(c);
  assert.equal(Buffer.concat(chunks).toString(), `>${header}\n${full}\n`);
  const choices = await page
    .getByLabel("Storage location")
    .locator("option")
    .allTextContents();
  if (choices.length > 1) {
    const values = await page
      .getByLabel("Storage location")
      .locator("option")
      .evaluateAll((nodes) => nodes.map((n) => n.value));
    await page
      .getByLabel("Storage location")
      .selectOption(values.find((v) => v !== location));
    await ready();
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .locator(".dna-explorer")
    .screenshot({ path: output + "visual-dna-mobile.png" });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  );
  assert.deepEqual(errors, []);
  assert.deepEqual(mutations, []);
  console.log(
    "PASS: FASTA export, location switching, mobile layout, no page errors and no archive writes.",
  );
} finally {
  await browser.close();
}
