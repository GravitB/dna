/* Beat 10 — close. The ask, and the last frame of the page.
 *
 * The lockup draws itself: the two helix strands sweep out, the base pairs drop
 * in between them, their letters arrive, and then the Lazarus wordmark rises in.
 *
 * Nothing in this scene fades out. It is the last thing a visitor sees, so it
 * assembles, lands by about p = 0.76, and then holds. update(p) is pure. The only
 * motion that is not driven by p is one slow ambient breath behind the mark, and
 * it does not run when ctx.reduced is true.
 */

const NS = 'http://www.w3.org/2000/svg';

const MUTED = '#3E6B52';
const INK = '#08130B';
const AUDIT = '#0B6E82';

/* the helix mark */
const HELIX = '#32C7DB';
const BASE_LETTER = '#101418';
const WORD_FILL = '#08130B';

const MARK_W = 434;          /* the lockup's full width */
const MARK_H = 154;          /* outer edge of the ribbon, top to bottom */
const MARK_TOP = 76.25;      /* where that outer edge sits in lockup coords */
const MARK_AXIS = 153.25;    /* the helix centre line */
const MARK_SW = 25;

const STRAND_1 = 'M0 206.05C31.05 206.05 77.05 194.96 115 153.25C148.66 102.29 189.46 88.75 217 88.75C244.54 88.75 285.34 102.29 319 153.25C356.95 194.96 402.95 206.05 434 206.05';
const STRAND_2 = 'M0 100.45C31.05 100.45 77.05 111.54 115 153.25C148.66 204.21 189.46 217.75 217 217.75C244.54 217.75 285.34 204.21 319 153.25C356.95 111.54 402.95 100.45 434 100.45';

/* x, y, width, height, fill, upper letter, lower letter. The two pairs under
 * each crossing carry no letters, exactly as the artwork has them. */
const BASES = [
  [17, 101, 22.5, 89, '#FC68D6', '', ''],
  [53.5, 105.5, 22.5, 72, '#FEC746', '', ''],
  [159, 119, 22.5, 86, '#FEC746', 'A', 'T'],
  [195, 103.5, 23, 114.5, '#5BD67C', 'G', 'C'],
  [231.5, 104, 23, 113.5, '#FC68D6', 'C', 'G'],
  [267.5, 120.5, 23, 85, '#5BD67C', 'T', 'A'],
  [365.5, 105.5, 23, 76, '#FC68D6', '', ''],
  [400, 101, 22.5, 90, '#FEC746', '', ''],
];
const LETTER_SIZE = 28.5;   /* cap height 20.5, as in the file */
const LETTER_TOP = 148.75;
const LETTER_BOT = 185.75;

/* The wordmark is set as text, one tspan per letter so the letters can arrive
 * one after another. */
const WORD = 'Lazarus';

const SANS = "'Instrument Sans','Lazarus Sans',system-ui,-apple-system,'Segoe UI',sans-serif";

const REPO = 'https://github.com/GravitB/dna';
const APP = '/app/';

function e(tag, attrs, parent) {
  const n = document.createElementNS(NS, tag);
  if (attrs) for (const k in attrs) n.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(n);
  return n;
}
const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
const seg = (p, a, b) => clamp((p - a) / (b - a), 0, 1);
const smooth = (t) => t * t * (3 - 2 * t);

const S = {
  root: null, svg: null, ctx: null, reduced: false, mode: '', p: 0, L: null, parts: null, raf: 0,
};

/* The shell hands the same ctx object to every scene and mutates ctx.reduced
 * when the setting changes, so read it per frame rather than latching it. */
function red() {
  S.reduced = !!(S.ctx && S.ctx.reduced);
  return S.reduced;
}

/* The close scene gets the whole stage: 1324 by 900 on a desktop, 354 by 844 on
 * a phone. The viewBox follows that aspect so the lockup fills the frame. */
function layout(mode) {
  if (mode === 'narrow') {
    return {
      vw: 720, vh: 1460, narrow: true,
      markSize: 580, markX: 360, markY: 470,
      wordY: 840,
      linkSize: 30, linkY: 962,
    };
  }
  return {
    vw: 1200, vh: 820, narrow: false,
    markSize: 512, markX: 600, markY: 200,
    wordY: 512,
    linkSize: 22, linkY: 606,
  };
}

function build() {
  const L = S.L, svg = S.svg;
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  svg.setAttribute('viewBox', '0 0 ' + L.vw + ' ' + L.vh);

  const k = L.markSize / MARK_W;

  const defs = e('defs', null, svg);
  const halo = e('radialGradient', { id: 'eg-close-halo', cx: '0.5', cy: '0.5', r: '0.5' }, defs);
  e('stop', { offset: '0', 'stop-color': AUDIT, 'stop-opacity': '0.16' }, halo);
  e('stop', { offset: '0.55', 'stop-color': AUDIT, 'stop-opacity': '0.05' }, halo);
  e('stop', { offset: '1', 'stop-color': AUDIT, 'stop-opacity': '0' }, halo);

  const glow = e('ellipse', {
    cx: L.markX, cy: L.markY + (L.markSize * MARK_H) / (2 * MARK_W),
    rx: L.markSize * 1.3, ry: L.markSize * 1.3,
    fill: 'url(#eg-close-halo)', opacity: '0',
  }, svg);

  /* the mark, drawn in the lockup's coordinates and scaled to markSize */
  const mark = e('g', {
    transform: 'translate(' + (L.markX - L.markSize / 2) + ',' + L.markY + ') scale(' + k + ')',
  }, svg);
  const crop = e('g', { transform: 'translate(0,' + (-MARK_TOP) + ')' }, mark);
  const strandA = e('path', {
    d: STRAND_1, fill: 'none', stroke: HELIX, 'stroke-width': MARK_SW,
    pathLength: '1', 'stroke-dasharray': '1 2', 'stroke-dashoffset': '1',
  }, crop);
  const strandC = e('path', {
    d: STRAND_2, fill: 'none', stroke: HELIX, 'stroke-width': MARK_SW,
    pathLength: '1', 'stroke-dasharray': '1 2', 'stroke-dashoffset': '1',
  }, crop);

  /* each base pair is one group, so the capsule and its two letters arrive
   * together and can be scaled about the helix centre line */
  const bases = BASES.map(function (b) {
    const x = b[0], y = b[1], w = b[2], h = b[3], fill = b[4];
    const cx = x + w / 2;
    const g = e('g', {
      opacity: '0',
      transform: 'translate(' + cx + ',' + MARK_AXIS + ') scale(1,0) translate(' + (-cx) + ',' + (-MARK_AXIS) + ')',
    }, crop);
    e('rect', { x: x, y: y, width: w, height: h, rx: w / 2, fill: fill }, g);
    const pairs = [[b[5], LETTER_TOP], [b[6], LETTER_BOT]];
    for (const pr of pairs) {
      if (!pr[0]) continue;
      const t = e('text', {
        x: cx, y: pr[1], 'text-anchor': 'middle', 'font-family': SANS,
        'font-size': LETTER_SIZE, 'font-weight': '700', fill: BASE_LETTER,
      }, g);
      t.textContent = pr[0];
    }
    return { g: g, cx: cx };
  });

  /* the wordmark. Its letters arrive one after another, the same beat as the
   * base pairs dropping into the helix above them. */
  const word = e('text', {
    x: L.markX, y: L.wordY, 'text-anchor': 'middle', 'font-family': SANS,
    'font-size': L.narrow ? 132 : 104, 'font-weight': '600', 'letter-spacing': '-2',
    fill: WORD_FILL,
  }, svg);
  const glyphs = WORD.split('').map(function (ch) {
    const t = e('tspan', { opacity: '0' }, word);
    t.textContent = ch;
    return t;
  });
  const rise = 14;

  /* links, one centred line so the browser does the measuring */
  const links = e('text', {
    x: L.markX, y: L.linkY, 'text-anchor': 'middle', 'font-family': SANS,
    'font-size': L.linkSize, fill: MUTED, opacity: '0',
  }, svg);
  const anchors = [];
  const addLink = function (href, label) {
    const a = e('a', { href: href, target: '_blank', rel: 'noopener' }, links);
    const t = e('tspan', { fill: AUDIT, 'text-decoration': 'underline', 'font-weight': '500' }, a);
    t.textContent = label;
    anchors.push({ a: a, t: t });
  };
  addLink(REPO, 'Read the code');
  const sepA = e('tspan', { fill: MUTED }, links);
  sepA.textContent = '  ·  ';
  addLink(APP, 'Open the business workspace');

  S.parts = { glow: glow, mark: mark, strandA: strandA, strandC: strandC, bases: bases,
    glyphs: glyphs, word: word, rise: rise, links: links, anchors: anchors };

  /* hover feedback without touching global styles */
  for (const an of anchors) {
    an.a.addEventListener('mouseenter', function () { an.t.setAttribute('fill', INK); });
    an.a.addEventListener('mouseleave', function () { an.t.setAttribute('fill', AUDIT); });
  }
}

function render(p) {
  const P = S.parts;
  if (!P) return;

  P.strandA.setAttribute('stroke-dashoffset', 1 - smooth(seg(p, 0.00, 0.24)));
  P.strandC.setAttribute('stroke-dashoffset', 1 - smooth(seg(p, 0.04, 0.28)));

  /* the base pairs drop in left to right once the strands are most of the way */
  P.bases.forEach(function (b, i) {
    const t = smooth(seg(p, 0.18 + i * 0.026, 0.34 + i * 0.026));
    b.g.setAttribute('opacity', t.toFixed(3));
    b.g.setAttribute('transform',
      'translate(' + b.cx + ',' + MARK_AXIS + ') scale(1,' + t.toFixed(3) + ') translate('
      + (-b.cx) + ',' + (-MARK_AXIS) + ')');
  });

  /* the wordmark rises in, letter by letter, and stays. Nothing fades back out. */
  let last = 0;
  P.glyphs.forEach(function (g, i) {
    const t = smooth(seg(p, 0.42 + i * 0.026, 0.60 + i * 0.026));
    g.setAttribute('opacity', t.toFixed(3));
    last = t;
  });
  P.word.setAttribute('transform', 'translate(0,' + ((1 - last) * P.rise).toFixed(1) + ')');

  const linkIn = smooth(seg(p, 0.60, 0.76));
  P.links.setAttribute('opacity', linkIn.toFixed(3));
  P.links.setAttribute('transform', 'translate(0,' + ((1 - linkIn) * 12).toFixed(2) + ')');

  S.glowBase = smooth(seg(p, 0.05, 0.45));
  if (S.reduced) P.glow.setAttribute('opacity', S.glowBase);
}

/* ambient only: one slow breath behind the mark, never part of the story */
function ambient(now) {
  S.raf = requestAnimationFrame(ambient);
  if (!S.parts) return;
  const b = S.glowBase || 0;
  if (S.ctx && S.ctx.reduced) { S.parts.glow.setAttribute('opacity', b); return; }
  S.parts.glow.setAttribute('opacity', (b * (0.72 + 0.28 * (0.5 + 0.5 * Math.sin(now / 1700)))).toFixed(3));
}

export default {
  id: 'close',

  mount(root, ctx) {
    S.root = root;
    S.ctx = ctx || {};
    red();
    S.svg = e('svg', {
      xmlns: NS, viewBox: '0 0 1200 820', preserveAspectRatio: 'xMidYMid meet',
      role: 'img', 'aria-label': 'Lazarus. Read the code, open the business workspace.',
    });
    S.svg.style.width = '100%';
    S.svg.style.height = '100%';
    S.svg.style.display = 'block';
    root.appendChild(S.svg);
    S.mode = 'wide';
    S.L = layout(S.mode);
    build();
    render(S.reduced ? 1 : 0);
    if (!S.reduced) S.raf = requestAnimationFrame(ambient);
  },

  update(p) {
    S.p = p;
    render(red() ? 1 : clamp(p, 0, 1));
  },

  resize(w, h) {
    const mode = w < 620 ? 'narrow' : 'wide';
    if (mode === S.mode) return;
    S.mode = mode;
    S.L = layout(mode);
    build();
    render(red() ? 1 : clamp(S.p, 0, 1));
  },

  unmount() {
    if (S.raf) cancelAnimationFrame(S.raf);
    S.raf = 0;
    if (S.svg && S.svg.parentNode) S.svg.parentNode.removeChild(S.svg);
    S.svg = null; S.parts = null;
  },
};
