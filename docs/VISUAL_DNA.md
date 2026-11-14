# DNA viewer

Open an approved archive, then select **Explore your DNA** under **Your records, written as DNA**. Choose a storage location, data group, and strand. The viewer uses that location's saved `order.fasta`, including its actual strand identifiers and A/C/G/T sequence. The manifest is available as a separate group.

The default view shows 30 bases. Move the range slider, select a letter, or choose **Whole strand** to inspect more. Drag to rotate, scroll to zoom, or use the camera buttons. **Build strand visually** animates the selected region; reduced-motion preferences skip the animation. **Download this strand (FASTA)** exports the complete original strand, even while viewing a close-up.

The optional second strand is a generated complement for the illustration. It is not an additional stored archive strand. Coordinates are idealized oxView geometry, not a prediction of physical folding or a molecular-dynamics experiment. Recovery results and the certificate remain the evidence of recoverability.

## Integration

- React fetches DNA through the existing `/api/jobs/{id}/files/vaults/vault-{number}/order.fasta` backend route. It works with the configured local or Supabase artifact store; no database schema or backend dependency changes are required.
- oxView runs locally at `/oxview/index.html` inside an iframe. The renderer loads only when the viewer is expanded. Sequence and camera messages require the same-origin parent; render confirmations must match the active sequence, range, and complement setting.
- The embed disables tracking, external import, editing shortcuts, and network connections. Opening or animating a model does not write to the archive.
- Invalid FASTA and unavailable locations produce a message rather than a substitute sequence. If WebGL is unavailable, the exact letters and FASTA export remain usable.
- Pinned upstream revision, GPL license, source files, and integration modifications are in [the oxView notice](../web/public/oxview/LAZARUS-NOTICE.md). `python3 scripts/vendor_oxview.py` reproduces the pinned source/runtime assets; it preserves the Lazarus bridge and styles.

## Verification

```bash
npm ci --prefix web
npm test --prefix web
npm run build --prefix web
```

With the backend running and an existing approved archive:

```bash
npx --prefix web playwright install chromium
npm run test:visual --prefix web
```

Alternatively, set `CHROME_EXECUTABLE` to an installed Chrome executable. Optional `LAZARUS_TEST_URL` and `LAZARUS_ARCHIVE_ID` select the running server and archive. Defaults are `http://127.0.0.1:8000` and the first available approved archive.

The read-only browser check compares native oxView bases to saved FASTA, exercises close-up/full views, base selection, animation, single-strand mode, FASTA download, and location switching. It also checks mobile overflow, page errors, and absence of archive writes. Desktop and mobile screenshots are saved under the ignored `scratch/` directory.
