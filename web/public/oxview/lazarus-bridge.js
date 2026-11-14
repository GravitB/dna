/* Lazarus integration code, GPL-3.0-or-later. No network requests or archive writes. */
(() => {
  const origin = location.origin;
  const send = (type, extra = {}) =>
    window.parent.postMessage({ type, ...extra }, origin);
  let bases = [],
    sequence = "",
    timer = null,
    start = 0;
  const cancel = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  };
  function fit() {
    if (!bases.length) return;
    const bounds = new THREE.Box3().setFromPoints(bases.map((b) => b.getPos()));
    const center = bounds.getCenter(new THREE.Vector3());
    const span = bounds.getSize(new THREE.Vector3());
    const distance =
      ((Math.max(8, span.length() / 2) /
        Math.sin((camera.fov * Math.PI) / 360)) *
        1.2) /
      Math.min(1, innerWidth / innerHeight);
    controls.target.copy(center);
    camera.up.set(0, 0, 1);
    camera.position
      .copy(center)
      .add(new THREE.Vector3(distance, distance * 0.1, distance * 0.08));
    camera.lookAt(center);
    controls.update();
    render();
  }
  function draw(input, duplex) {
    resetScene(false);
    edit.createStrand(input, duplex, false);
    bases = systems[0].strands[0].getMonomers();
    if (bases.map((b) => b.type).join("") !== input)
      throw new Error("Rendered sequence does not match the archive.");
    render();
  }
  function setSequence(data) {
    cancel();
    if (
      typeof data.sequence !== "string" ||
      !/^[ACGT]{1,1000}$/.test(data.sequence)
    )
      throw new Error("Invalid DNA sequence.");
    sequence = data.sequence;
    start = Number.isInteger(data.start)
      ? Math.max(0, Math.min(data.start, sequence.length - 1))
      : 0;
    const end = Number.isInteger(data.length)
      ? Math.min(sequence.length, start + Math.max(1, data.length))
      : sequence.length;
    const region = sequence.slice(start, end);
    draw(region, Boolean(data.duplex));
    fit();
    if (
      !data.animate ||
      matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      send("lazarus-oxview-rendered", {
        sequence,
        requestId: data.requestId,
        renderedSequence: region,
        start,
        bases: region.length,
      });
      return;
    }
    const full = region;
    let count = 0;
    const step = () => {
      try {
        count = Math.min(
          full.length,
          count + Math.max(1, Math.ceil(full.length / 22)),
        );
        draw(full.slice(0, count), Boolean(data.duplex));
        send("lazarus-oxview-building", {
          count,
          total: full.length,
          requestId: data.requestId,
        });
        if (count < full.length) timer = setTimeout(step, 40);
        else {
          timer = null;
          send("lazarus-oxview-rendered", {
            sequence,
            requestId: data.requestId,
            renderedSequence: full,
            start,
            bases: full.length,
          });
        }
      } catch (e) {
        send("lazarus-oxview-error", { error: e.message });
      }
    };
    step();
  }
  window.addEventListener("message", (event) => {
    if (
      event.source !== window.parent ||
      event.origin !== origin ||
      !event.data ||
      typeof event.data.type !== "string"
    )
      return;
    try {
      const d = event.data;
      if (d.type === "lazarus-oxview-set") setSequence(d);
      if (
        d.type === "lazarus-oxview-select" &&
        Number.isInteger(d.index) &&
        d.index >= start &&
        d.index - start < bases.length
      )
        api.selectElements([bases[d.index - start]], false);
      if (d.type === "lazarus-oxview-control" && bases.length) {
        const offset = camera.position.clone().sub(controls.target);
        if (d.action === "reset") fit();
        else if (d.action === "left" || d.action === "right") {
          offset.applyAxisAngle(camera.up, d.action === "left" ? -0.25 : 0.25);
          camera.position.copy(controls.target).add(offset);
        } else if (d.action === "in" || d.action === "out") {
          const scale = d.action === "in" ? 0.85 : 1.18;
          if (offset.length() * scale >= 3 && offset.length() * scale <= 3000)
            camera.position
              .copy(controls.target)
              .add(offset.multiplyScalar(scale));
        }
        controls.update();
        render();
      }
    } catch (e) {
      send("lazarus-oxview-error", { error: e.message });
    }
  });
  window.addEventListener("load", () => {
    try {
      if (
        typeof renderer === "undefined" ||
        !renderer ||
        typeof edit?.createStrand !== "function"
      )
        throw new Error(
          "3D rendering is unavailable. Enable WebGL or use the sequence and download below.",
        );
      canvas.setAttribute(
        "aria-label",
        "Interactive 3D model of the selected archive DNA strand. Drag to rotate and scroll to zoom.",
      );
      setArrowsVisibility(false);
      onWindowResize();
      send("lazarus-oxview-ready");
    } catch (e) {
      send("lazarus-oxview-error", { error: e.message });
    }
  });
  window.addEventListener("pagehide", cancel);
})();
