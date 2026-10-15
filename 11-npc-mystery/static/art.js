// Drawn art for The Dark Lamp at Saltmarsh: the harbour at dusk, the inn's back room, the three
// portraits and a few small icons. Plain SVG strings, drawn for this game.

const INK = "#2a2018";

// a small seeded random, so the waves and stones fall the same way every time
function rng(seed) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}

function waves(seed, y0, y1, x0, x1, n) {
  const r = rng(seed);
  let out = "";
  for (let i = 0; i < n; i++) {
    const t = r();
    const y = y0 + (y1 - y0) * Math.pow(t, 0.8);
    const near = (y - y0) / (y1 - y0);
    const len = 14 + near * 60 * r();
    const x = x0 + (x1 - x0) * r();
    const op = (0.08 + 0.22 * r()).toFixed(2);
    out += `<path d="M${x.toFixed(0)} ${y.toFixed(0)} q${(len / 2).toFixed(0)} -${(1.5 + near * 2).toFixed(1)} ${len.toFixed(0)} 0" stroke="#a9c3c2" stroke-opacity="${op}" stroke-width="${(1 + near * 1.6).toFixed(1)}" fill="none" stroke-linecap="round"/>`;
  }
  return out;
}

function stones(seed, x0, x1, y0, y1) {
  const r = rng(seed);
  let out = "";
  for (let y = y0; y < y1; y += 16) {
    const shift = ((y - y0) / 16) % 2 ? 0 : 18;
    for (let x = x0 - shift; x < x1; x += 30 + r() * 14) {
      out += `<path d="M${x.toFixed(0)} ${y} v16" stroke="#2c2b27" stroke-opacity=".55" stroke-width="1.4"/>`;
    }
    out += `<path d="M${x0} ${y} H${x1}" stroke="#2c2b27" stroke-opacity=".45" stroke-width="1.4"/>`;
  }
  return out;
}

function stars(seed, n) {
  const r = rng(seed);
  let out = "";
  for (let i = 0; i < n; i++) {
    out += `<circle cx="${(-300 + r() * 2400).toFixed(0)}" cy="${(r() * 260).toFixed(0)}" r="${(0.8 + r() * 1.3).toFixed(1)}" fill="#f4ead2" opacity="${(0.25 + r() * 0.5).toFixed(2)}"/>`;
  }
  return out;
}

const GRAIN = `
  <filter id="grain" x="0" y="0" width="100%" height="100%">
    <feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" seed="7" result="n"/>
    <feColorMatrix in="n" type="matrix" values="0 0 0 0 .15  0 0 0 0 .12  0 0 0 0 .08  0 0 0 .55 0"/>
  </filter>`;

// ---- the harbour ------------------------------------------------------------------------
// viewBox 0 0 1600 900; drawn wider than the box (-500..2300) so the camera can move about.
export function harbour() {
  return `
<svg viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
<defs>
  <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#121d26"/><stop offset=".45" stop-color="#26394a"/>
    <stop offset=".78" stop-color="#5a6466"/><stop offset=".93" stop-color="#b3825f"/><stop offset="1" stop-color="#d49c70"/>
  </linearGradient>
  <linearGradient id="sea" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#4b5d5f"/><stop offset=".08" stop-color="#2b4650"/><stop offset="1" stop-color="#0f2129"/>
  </linearGradient>
  <linearGradient id="beam" x1="1" y1="0" x2="0" y2="0">
    <stop offset="0" stop-color="#ffe2a0" stop-opacity=".75"/><stop offset="1" stop-color="#ffe2a0" stop-opacity="0"/>
  </linearGradient>
  <radialGradient id="glow"><stop offset="0" stop-color="#ffcf7a" stop-opacity=".9"/><stop offset="1" stop-color="#ffcf7a" stop-opacity="0"/></radialGradient>
  <radialGradient id="moonglow"><stop offset="0" stop-color="#f2e6c8" stop-opacity=".45"/><stop offset="1" stop-color="#f2e6c8" stop-opacity="0"/></radialGradient>
  <linearGradient id="tower" x1="0" x2="1"><stop offset="0" stop-color="#d9d0bd"/><stop offset=".6" stop-color="#ece5d4"/><stop offset="1" stop-color="#a59d8c"/></linearGradient>
  <clipPath id="towerclip"><path d="M1248 400 L1258 212 L1302 212 L1312 400 Z"/></clipPath>
  ${GRAIN}
</defs>
<g id="cam">
  <rect x="-600" y="-300" width="3000" height="790" fill="url(#sky)"/>
  ${stars(11, 70)}
  <circle cx="300" cy="118" r="90" fill="url(#moonglow)"/>
  <circle cx="300" cy="118" r="28" fill="#efe4c8"/>
  <path d="M286 106 a6 6 0 1 0 1 0 M308 128 a4 4 0 1 0 1 0" fill="#d9ccab" opacity=".7"/>
  <path d="M-300 210 C -100 196 120 200 360 214 C 470 220 600 206 760 214 L 760 226 C 520 236 120 236 -300 232 Z" fill="#1d2b36" opacity=".8"/>
  <path d="M520 150 C 640 140 760 144 900 152 C 980 156 1080 150 1180 156 L 1180 166 C 1000 172 760 170 520 164 Z" fill="#1d2b36" opacity=".6"/>
  <path d="M-400 300 C -200 292 0 294 200 300 L 200 308 C 0 312 -200 310 -400 308 Z" fill="#3a4a52" opacity=".5"/>
  <path d="M-500 482 L -500 452 C -300 446 -100 444 60 450 C 160 454 240 462 320 472 L 380 482 Z" fill="#2b3a42"/>

  <rect x="-600" y="480" width="3000" height="720" fill="url(#sea)"/>
  <rect x="-600" y="480" width="3000" height="10" fill="#c99467" opacity=".22"/>
  ${waves(3, 490, 1080, -500, 2300, 520)}
  <g opacity=".55">${[0, 1, 2, 3, 4, 5, 6, 7].map((i) => `<rect x="${292 - i * 1.5}" y="${492 + i * 22}" width="${16 + i * 3}" height="2.5" rx="1" fill="#efe4c8" opacity="${(0.8 - i * 0.08).toFixed(2)}"/>`).join("")}</g>

  <!-- the Teeth -->
  <path d="M780 602 L796 578 L806 590 L822 562 L834 592 L850 572 L862 598 L878 584 L894 604 Z" fill="#141e23" stroke="#0b1216" stroke-width="2"/>
  <path d="M772 604 q20 -5 40 0 t40 0 t40 0 t40 0" stroke="#d5e2df" stroke-opacity=".5" stroke-width="2" fill="none"/>

  <!-- the headland and the light -->
  <path d="M1040 482 C 1070 446 1110 420 1160 410 C 1210 400 1260 397 1320 399 L 2300 380 L 2300 1200 L 1250 1200 C 1210 900 1120 620 1040 482 Z" fill="#232e34"/>
  <path d="M1076 470 C 1100 446 1130 430 1170 424 L 1196 470 C 1160 540 1140 620 1150 760 L 1124 760 C 1110 640 1096 540 1076 470 Z" fill="#2f3c43"/>
  <path d="M1200 420 C 1240 440 1260 500 1250 600 L 1232 600 C 1238 520 1226 460 1200 420 Z" fill="#2c383e"/>
  <path d="M1044 476 C 1076 442 1112 420 1160 410 C 1210 400 1262 396 1320 398 L 2300 379 L 2300 394 L 1320 412 C 1262 410 1210 414 1164 424 C 1118 434 1082 452 1056 486 Z" fill="#46553d"/>
  <path d="M1230 404 C 1180 432 1138 470 1110 520 C 1086 566 1060 600 1004 628" stroke="#8a8467" stroke-width="2.2" stroke-dasharray="5 7" fill="none" opacity=".7"/>
  <polygon class="beam" points="1280,174 520,96 520,268 1280,186" fill="url(#beam)"/>
  <circle cx="1280" cy="180" r="70" fill="url(#glow)" opacity=".55"/>
  <g stroke="${INK}" stroke-width="2.2" stroke-linejoin="round">
    <path d="M1248 400 L1258 212 L1302 212 L1312 400 Z" fill="url(#tower)"/>
    <g clip-path="url(#towerclip)" stroke="none"><rect x="1240" y="246" width="80" height="30" fill="#8f3a2b"/><rect x="1240" y="318" width="80" height="30" fill="#8f3a2b"/></g>
    <path d="M1248 400 L1258 212 L1302 212 L1312 400 Z" fill="none"/>
    <rect x="1250" y="204" width="60" height="9" fill="#2b2522"/>
    <path d="M1252 204 v-12 M1262 204 v-12 M1272 204 v-12 M1288 204 v-12 M1298 204 v-12 M1308 204 v-12 M1250 192 h60" stroke-width="1.6" fill="none"/>
    <rect x="1264" y="160" width="32" height="32" fill="#ffd98a"/>
    <path d="M1274 160 v32 M1286 160 v32" stroke-width="1.6"/>
    <path d="M1260 160 Q1280 132 1300 160 Z" fill="#2b2522"/>
    <path d="M1280 140 v-10" stroke-width="2"/><circle cx="1280" cy="128" r="3" fill="#2b2522"/>
    <path d="M1272 400 v-26 a8 8 0 0 1 16 0 v26 Z" fill="#3a2b22"/>
    <rect x="1276" y="292" width="8" height="16" fill="#2b2522"/>
    <path d="M1326 402 v-34 h70 v32 Z" fill="#cfc6b2"/>
    <path d="M1320 370 L1361 346 L1402 370 Z" fill="#4a3a33"/>
    <rect x="1340" y="378" width="14" height="14" fill="#f2b552"/>
  </g>

  <!-- the quay -->
  <rect x="-600" y="640" width="1600" height="120" fill="#4b4a43"/>
  <rect x="-600" y="636" width="1600" height="10" fill="#6b685c"/>
  ${stones(5, -600, 1000, 646, 760)}
  <rect x="-600" y="760" width="1600" height="12" fill="#2f2e2a"/>
  <path d="M-600 772 H1000" stroke="#a9c3c2" stroke-opacity=".25" stroke-width="2"/>

  <!-- the harbour office -->
  <g stroke="${INK}" stroke-width="2.2" stroke-linejoin="round">
    <rect x="60" y="520" width="172" height="120" fill="#b4a88f"/>
    <path d="M48 524 L146 462 L244 524 Z" fill="#3b444b"/>
    <path d="M70 512 L146 470 L222 512" fill="none" stroke="#2c3338" stroke-width="1.4"/>
    <rect x="92" y="528" width="108" height="14" fill="#2e383e"/>
    <rect x="76" y="552" width="34" height="34" fill="#d8b46c" fill-opacity=".75"/>
    <path d="M93 552 v34 M76 569 h34" stroke-width="1.6"/>
    <rect x="182" y="552" width="34" height="34" fill="#2b3338"/>
    <path d="M199 552 v34 M182 569 h34" stroke-width="1.6"/>
    <rect x="128" y="590" width="34" height="50" fill="#3b2c22"/>
  </g>
  <text x="146" y="539" fill="#e7dcc2" font-family="IM Fell English SC, serif" font-size="10" text-anchor="middle" letter-spacing="1.5">Harbour Office</text>

  <!-- the Gull & Lantern -->
  <ellipse cx="420" cy="660" rx="180" ry="16" fill="#f2b552" opacity=".16"/>
  <g stroke="${INK}" stroke-width="2.2" stroke-linejoin="round">
    <rect x="514" y="384" width="34" height="70" fill="#5c4a3f"/>
    <rect x="510" y="378" width="42" height="10" fill="#4a3a31"/>
    <rect x="262" y="470" width="340" height="170" fill="#d6cbb1"/>
    <path d="M244 476 L432 378 L620 476 Z" fill="#6a3a2a"/>
    <path d="M276 466 L432 386 L588 466" fill="none" stroke="#4e2a1e" stroke-width="1.4"/>
    <rect x="262" y="544" width="340" height="8" fill="#4a362a"/>
    <g fill="#f2b552"><rect x="294" y="490" width="40" height="40"/><rect x="412" y="490" width="40" height="40"/><rect x="530" y="490" width="40" height="40"/></g>
    <path d="M314 490 v40 M294 510 h40 M432 490 v40 M412 510 h40 M550 490 v40 M530 510 h40" stroke-width="1.6"/>
    <rect x="286" y="574" width="96" height="50" fill="#f6c165"/>
    <path d="M310 574 v50 M334 574 v50 M358 574 v50 M286 599 h96" stroke-width="1.6"/>
    <rect x="484" y="574" width="96" height="50" fill="#f6c165"/>
    <path d="M508 574 v50 M532 574 v50 M556 574 v50 M484 599 h96" stroke-width="1.6"/>
    <path d="M412 640 v-58 a20 20 0 0 1 40 0 v58 Z" fill="#4a2c20"/>
    <path d="M416 580 a16 16 0 0 1 32 0 Z" fill="#f6c165"/>
    <rect x="300" y="553" width="264" height="16" fill="#2b2420"/>
    <path d="M602 514 h56 M612 514 l-10 14" fill="none" stroke-width="3"/>
    <rect x="620" y="522" width="52" height="44" fill="#3a2a20"/>
    <path d="M630 538 c8 -8 14 -2 16 4 c4 -8 12 -10 18 -4" fill="none" stroke="#e9c97a" stroke-width="2.4"/>
    <path d="M643 548 h10 v10 h-10 Z" fill="#e9c97a" stroke="#e9c97a" stroke-width="1"/>
  </g>
  <g fill="#ffcf7a" opacity=".22"><circle cx="314" cy="510" r="34"/><circle cx="432" cy="510" r="34"/><circle cx="550" cy="510" r="34"/><circle cx="334" cy="599" r="48"/><circle cx="532" cy="599" r="48"/></g>
  <text x="432" y="565" fill="#e9c97a" font-family="IM Fell English SC, serif" font-size="13" text-anchor="middle" letter-spacing="2.5">The Gull &amp; Lantern</text>
  <path class="smoke" d="M531 376 c-10 -20 14 -28 4 -48 c-8 -16 12 -26 6 -44" stroke="#c9c4b6" stroke-opacity=".35" stroke-width="6" fill="none" stroke-linecap="round"/>

  <!-- cottages -->
  <g stroke="${INK}" stroke-width="2.2" stroke-linejoin="round">
    <rect x="640" y="560" width="110" height="80" fill="#9aa39b"/>
    <path d="M630 564 L695 518 L760 564 Z" fill="#383d44"/>
    <rect x="658" y="584" width="26" height="26" fill="#f2b552"/><rect x="706" y="590" width="24" height="50" fill="#3b2c22"/>
    <rect x="766" y="576" width="96" height="64" fill="#a99f8c"/>
    <path d="M756 580 L814 540 L872 580 Z" fill="#3d3a40"/>
    <rect x="782" y="594" width="24" height="24" fill="#2b3338"/><rect x="826" y="594" width="24" height="24" fill="#f2b552" fill-opacity=".8"/>
  </g>

  <!-- the ferry landing -->
  <g stroke="${INK}" stroke-width="2.2" stroke-linejoin="round">
    <path d="M990 646 h170 v12 h-170 Z" fill="#6b5640"/>
    <path d="M1004 658 v62 M1050 658 v66 M1096 658 v62 M1142 658 v66" stroke="#3a2e25" stroke-width="8"/>
    <path d="M1150 646 v-58" stroke-width="4"/>
    <rect x="1140" y="574" width="20" height="18" fill="#ffd98a"/>
    <path d="M1136 574 h28 l-6 -8 h-16 Z" fill="#2b2522"/>
    <path d="M1010 690 C 1030 712 1110 714 1138 690 Z" fill="#5a3d2c"/>
    <path d="M1012 690 h126" stroke="#c9b38a" stroke-width="3"/>
    <path d="M1040 684 L1120 704 M1060 700 L1110 680" stroke="#8f7652" stroke-width="3"/>
    <path d="M1138 690 C 1146 676 1148 664 1150 652" fill="none" stroke="#c9b38a" stroke-width="1.8"/>
  </g>
  <circle cx="1150" cy="584" r="60" fill="url(#glow)" opacity=".55"/>
  <g opacity=".5">${[0, 1, 2, 3, 4].map((i) => `<rect x="${1144 - i}" y="${730 + i * 16}" width="${12 + i * 2}" height="2.5" fill="#ffd98a" opacity="${(0.7 - i * 0.12).toFixed(2)}"/>`).join("")}</g>
</g>
<rect x="0" y="0" width="1600" height="900" filter="url(#grain)" opacity=".5"/>
</svg>`;
}

// ---- the back room of the Gull & Lantern, later that evening -------------------------
export function innRoom() {
  const planks = Array.from({ length: 26 }, (_, i) => `<path d="M${i * 64} 0 V640" stroke="#2c1d14" stroke-width="2" opacity=".55"/>`).join("");
  const boards = Array.from({ length: 6 }, (_, i) => `<path d="M0 ${680 + i * 40} H1600" stroke="#2c1d14" stroke-width="2" opacity=".5"/>`).join("");
  const bottles = [
    [140, "#3f5a3a"], [176, "#6b3a2a"], [206, "#2f4450"], [240, "#5a4a2a"], [272, "#3f5a3a"], [304, "#7a5a2a"],
  ].map(([x, c], i) => `<path d="M${x} ${i % 2 ? 300 : 290} v-24 h6 v-14 h6 v14 h6 v24 Z" transform="translate(0 ${i % 2 ? 0 : 10})" fill="${c}" stroke="${INK}" stroke-width="1.8"/>`).join("");
  return `
<svg viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
<defs>
  <radialGradient id="fire" cx=".5" cy=".6"><stop offset="0" stop-color="#ffb347" stop-opacity=".8"/><stop offset="1" stop-color="#ffb347" stop-opacity="0"/></radialGradient>
  <radialGradient id="lamp"><stop offset="0" stop-color="#ffd27a" stop-opacity=".55"/><stop offset="1" stop-color="#ffd27a" stop-opacity="0"/></radialGradient>
  <radialGradient id="vig" cx=".5" cy=".45" r=".75"><stop offset=".55" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".6"/></radialGradient>
  <linearGradient id="win" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#141e28"/><stop offset=".62" stop-color="#2a3a46"/><stop offset=".63" stop-color="#1b2f37"/><stop offset="1" stop-color="#0f1f26"/></linearGradient>
  ${GRAIN}
</defs>
<rect width="1600" height="900" fill="#4a3022"/>
${planks}
<rect y="640" width="1600" height="260" fill="#3a251a"/>
${boards}
<rect y="630" width="1600" height="14" fill="#2c1b12"/>
<!-- the shelf and bottles -->
<rect x="110" y="300" width="240" height="10" fill="#2c1b12"/>
${bottles}
<!-- the window onto the harbour -->
<g stroke="${INK}" stroke-width="3">
  <rect x="640" y="150" width="300" height="240" fill="url(#win)"/>
  <circle cx="700" cy="200" r="14" fill="#efe4c8" stroke="none"/>
  <path d="M850 300 l6 -60 h12 l6 60 Z" fill="#d9d0bd" stroke-width="1.5"/>
  <rect x="852" y="232" width="20" height="10" fill="#ffd98a" stroke-width="1.5"/>
  <polygon class="beam" points="862,236 640,214 640,262 862,240" fill="#ffe2a0" opacity=".35" stroke="none"/>
  <path d="M790 150 v240 M640 270 h300" stroke="#3a2a20" stroke-width="10"/>
  <rect x="640" y="150" width="300" height="240" fill="none" stroke="#3a2a20" stroke-width="14"/>
  <rect x="624" y="388" width="332" height="16" fill="#3a2a20"/>
</g>
<!-- the hearth -->
<g stroke="${INK}" stroke-width="3">
  <rect x="1180" y="330" width="300" height="310" fill="#6b625a"/>
  <rect x="1160" y="310" width="340" height="28" fill="#3a2a20"/>
  <path d="M1230 640 v-180 a100 80 0 0 1 200 0 v180 Z" fill="#1a110c"/>
</g>
<ellipse cx="1330" cy="590" rx="190" ry="160" fill="url(#fire)" class="flicker"/>
<path class="flicker" d="M1290 630 c-6 -40 20 -50 16 -86 c22 24 28 50 22 70 c10 -14 14 -30 10 -46 c24 30 22 56 10 62 Z" fill="#f29a3a" stroke="#c4602a" stroke-width="2"/>
<path d="M1260 636 h140" stroke="#5a3a22" stroke-width="12" stroke-linecap="round"/>
<!-- the hanging lamp -->
<path d="M800 0 v60" stroke="#1a110c" stroke-width="3"/>
<circle cx="800" cy="92" r="180" fill="url(#lamp)"/>
<path d="M784 62 h32 l-4 44 h-24 Z" fill="#ffd98a" stroke="${INK}" stroke-width="3"/>
<!-- the bar, front left -->
<g stroke="${INK}" stroke-width="3"><rect x="-20" y="520" width="520" height="40" fill="#5a3a26"/><rect x="0" y="560" width="480" height="340" fill="#4a2e1e"/></g>
<rect x="0" y="0" width="1600" height="900" fill="url(#vig)"/>
<rect x="0" y="0" width="1600" height="900" filter="url(#grain)" opacity=".5"/>
</svg>`;
}

// ---- the portraits ------------------------------------------------------------------------
// viewBox 0 0 320 420; bust, facing a little to the viewer's right.
const S = `stroke="${INK}" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"`;

const KNIT = (id, c) => `<pattern id="${id}" width="12" height="10" patternUnits="userSpaceOnUse"><path d="M0 2 l6 5 l6 -5" stroke="${c}" fill="none" stroke-width="1.6"/></pattern>`;

function mara() {
  return `
<defs>${KNIT("knit-m", "#3b5638")}</defs>
<ellipse cx="166" cy="78" rx="42" ry="30" fill="#8e4426" ${S}/>
<path d="M136 74 C 150 58 184 58 200 74 M146 92 C 160 82 180 82 192 90" stroke="#6a301b" stroke-width="2" fill="none"/>
<path d="M96 196 C 84 132 112 88 162 86 C 216 86 240 130 228 200 C 224 224 216 240 208 248 L 114 248 C 104 232 98 216 96 196 Z" fill="#94462a" ${S}/>
<path d="M30 420 C 34 352 70 312 128 296 L 192 296 C 250 312 286 352 290 420 Z" fill="#ece0c6" ${S}/>
<path d="M134 226 L 134 290 C 146 302 174 302 186 290 L 186 226 Z" fill="#e2a982" ${S}/>
<path d="M134 248 C 150 266 170 266 186 248 L 186 232 L 134 232 Z" fill="#c88664" opacity=".55"/>
<path d="M124 298 C 136 326 148 336 160 340 C 172 336 184 326 196 298" fill="#e2a982" ${S}/>
<path d="M26 420 C 28 350 62 304 124 290 C 134 324 142 370 150 420 Z" fill="#4f6d4b" ${S}/>
<path d="M26 420 C 28 350 62 304 124 290 C 134 324 142 370 150 420 Z" fill="url(#knit-m)" opacity=".8"/>
<path d="M294 420 C 292 350 258 304 196 290 C 186 324 178 370 170 420 Z" fill="#4f6d4b" ${S}/>
<path d="M294 420 C 292 350 258 304 196 290 C 186 324 178 370 170 420 Z" fill="url(#knit-m)" opacity=".8"/>
<path d="M226 306 C 246 312 262 326 270 344 L 256 420 L 226 420 C 234 380 234 340 226 306 Z" fill="#efe6d2" ${S}/>
<path d="M240 340 L 262 344 M236 358 L 260 362" stroke="#a8482a" stroke-width="3"/>
<ellipse cx="101" cy="184" rx="10" ry="15" fill="#e2a982" ${S}/>
<ellipse cx="219" cy="184" rx="10" ry="15" fill="#e2a982" ${S}/>
<circle cx="101" cy="206" r="5" fill="none" stroke="#c9a24a" stroke-width="2.6"/>
<circle cx="219" cy="206" r="5" fill="none" stroke="#c9a24a" stroke-width="2.6"/>
<path d="M160 104 C 208 104 222 142 220 178 C 218 214 196 242 160 244 C 124 242 102 214 100 178 C 98 142 112 104 160 104 Z" fill="#ecb892" ${S}/>
<path d="M104 196 C 112 226 132 242 160 244 C 140 236 118 222 104 196 Z" fill="#d49a76" opacity=".6"/>
<path d="M100 188 C 92 136 118 98 162 96 C 206 96 230 132 222 192 C 216 162 204 134 182 122 C 166 142 134 148 112 152 C 106 162 102 174 100 188 Z" fill="#a4532f" ${S}/>
<path d="M118 136 C 140 126 162 118 182 122 M196 124 C 208 136 216 154 218 172" stroke="#7a3a20" stroke-width="2" fill="none"/>
<path d="M102 192 C 96 212 100 228 92 244" stroke="#a4532f" stroke-width="4" fill="none" stroke-linecap="round"/>
<path d="M124 162 C 132 154 146 153 154 158" stroke="#6e331c" stroke-width="4" fill="none" stroke-linecap="round"/>
<path d="M168 158 C 176 153 190 154 198 162" stroke="#6e331c" stroke-width="4" fill="none" stroke-linecap="round"/>
<ellipse cx="140" cy="179" rx="5.5" ry="6" fill="${INK}"/><circle cx="142" cy="177" r="1.6" fill="#fff"/>
<ellipse cx="182" cy="179" rx="5.5" ry="6" fill="${INK}"/><circle cx="184" cy="177" r="1.6" fill="#fff"/>
<path d="M131 187 C 137 191 145 191 150 187 M172 187 C 178 191 186 191 191 187" stroke="#b77756" stroke-width="2" fill="none"/>
<path d="M162 184 C 160 194 156 202 154 206 C 158 210 166 210 170 206" stroke="#a8684a" stroke-width="2.4" fill="none"/>
<ellipse cx="127" cy="206" rx="13" ry="8" fill="#e0796b" opacity=".35"/>
<ellipse cx="195" cy="206" rx="13" ry="8" fill="#e0796b" opacity=".35"/>
<path d="M140 220 C 150 234 172 234 182 220 C 170 225 152 225 140 220 Z" fill="#8a3a2c" stroke="${INK}" stroke-width="2.2" stroke-linejoin="round"/>
<path d="M146 222 C 156 225 166 225 176 222" stroke="#f4ead8" stroke-width="2.4" fill="none"/>`;
}

function tobias() {
  return `
<defs>${KNIT("knit-t", "#22383f")}
<pattern id="rib" width="7" height="30" patternUnits="userSpaceOnUse"><path d="M3.5 0 v30" stroke="#1e3239" stroke-width="2"/></pattern>
<pattern id="cable" width="22" height="30" patternUnits="userSpaceOnUse"><path d="M6 0 c-6 8 6 14 0 22 c-3 4 -2 6 0 8 M16 0 c6 8 -6 14 0 22 c3 4 2 6 0 8" stroke="#a89a7c" stroke-width="2" fill="none"/></pattern></defs>
<path d="M22 420 C 26 350 60 306 122 290 L 198 290 C 260 306 294 350 298 420 Z" fill="#c08a2a" ${S}/>
<path d="M60 330 C 70 360 74 392 72 420 M262 330 C 252 360 248 392 250 420" stroke="#94681c" stroke-width="2.4" fill="none"/>
<path d="M122 290 C 132 330 146 380 160 420 C 174 380 188 330 198 290 Z" fill="#cdbf9f" ${S}/>
<path d="M122 290 C 132 330 146 380 160 420 C 174 380 188 330 198 290 Z" fill="url(#cable)"/>
<path d="M128 252 C 126 300 194 300 192 252 L 198 292 C 182 312 138 312 122 292 Z" fill="#cdbf9f" ${S}/>
<path d="M134 270 v26 M144 274 v28 M154 276 v28 M166 276 v28 M176 274 v28 M186 270 v26" stroke="#a89a7c" stroke-width="1.8"/>
<path d="M122 290 C 102 280 92 258 96 236 C 110 258 128 270 142 300 Z" fill="#b07a1f" ${S}/>
<path d="M198 290 C 218 280 228 258 224 236 C 210 258 192 270 178 300 Z" fill="#b07a1f" ${S}/>
<path d="M120 340 l10 4 M116 372 l10 4 M200 340 l-10 4 M204 372 l-10 4" stroke="${INK}" stroke-width="3"/>
<ellipse cx="99" cy="196" rx="10" ry="15" fill="#d39d78" ${S}/>
<ellipse cx="221" cy="196" rx="10" ry="15" fill="#d39d78" ${S}/>
<path d="M160 106 C 212 106 226 142 224 180 C 224 216 204 248 160 250 C 116 248 96 216 96 180 C 94 142 108 106 160 106 Z" fill="#d9a582" ${S}/>
<path d="M98 182 C 98 242 124 292 160 296 C 196 292 222 242 222 182 C 216 206 204 220 192 222 C 178 214 142 214 128 222 C 116 220 104 206 98 182 Z" fill="#b5b1a6" ${S}/>
<path d="M112 236 c4 14 10 24 18 32 M130 254 c4 12 10 22 16 30 M190 254 c-4 12 -10 22 -16 30 M208 236 c-4 14 -10 24 -18 32 M160 262 v26" stroke="#8c887e" stroke-width="2" fill="none"/>
<path d="M134 222 C 144 210 156 212 160 216 C 164 212 176 210 186 222 C 178 228 168 226 160 224 C 152 226 142 228 134 222 Z" fill="#9d998f" ${S}/>
<path d="M148 236 C 154 238 166 238 172 236" stroke="#5a3a2e" stroke-width="3" fill="none"/>
<path d="M158 188 C 156 200 150 206 149 212 C 154 218 166 218 172 212 C 170 206 164 200 163 188" fill="#c98d6c" ${S}/>
<ellipse cx="128" cy="210" rx="12" ry="7" fill="#c6533f" opacity=".28"/>
<ellipse cx="192" cy="210" rx="12" ry="7" fill="#c6533f" opacity=".28"/>
<ellipse cx="138" cy="192" rx="5" ry="3.8" fill="${INK}"/>
<ellipse cx="182" cy="192" rx="5" ry="3.8" fill="${INK}"/>
<path d="M128 188 C 134 185 144 185 150 189 M170 189 C 176 185 186 185 192 188" stroke="${INK}" stroke-width="3" fill="none"/>
<path d="M118 194 l-6 -2 M118 199 l-6 2 M202 194 l6 -2 M202 199 l6 2" stroke="#9c6b52" stroke-width="1.6"/>
<path d="M120 178 L 154 182 L 152 189 L 122 186 Z" fill="#8f8b80" stroke="${INK}" stroke-width="1.8" stroke-linejoin="round"/>
<path d="M200 178 L 166 182 L 168 189 L 198 186 Z" fill="#8f8b80" stroke="${INK}" stroke-width="1.8" stroke-linejoin="round"/>
<path d="M152 168 v8 M168 168 v8" stroke="#b07e60" stroke-width="1.8"/>
<path d="M98 166 C 96 112 124 74 160 74 C 196 74 224 112 222 166 Z" fill="#2e4a56" ${S}/>
<path d="M98 166 C 96 112 124 74 160 74 C 196 74 224 112 222 166 Z" fill="url(#knit-t)" opacity=".7"/>
<path d="M92 152 C 120 142 200 142 228 152 L 226 174 C 200 166 120 166 94 174 Z" fill="#284049" ${S}/>
<path d="M92 152 C 120 142 200 142 228 152 L 226 174 C 200 166 120 166 94 174 Z" fill="url(#rib)" opacity=".8"/>
<path d="M98 176 C 92 188 94 200 100 208 M222 176 C 228 188 226 200 220 208" stroke="#cfccc2" stroke-width="5" fill="none" stroke-linecap="round"/>`;
}

function elsie() {
  return `
<defs><pattern id="tweed" width="6" height="6" patternUnits="userSpaceOnUse"><circle cx="1.5" cy="1.5" r=".9" fill="#7d8486"/><circle cx="4.5" cy="4.5" r=".9" fill="#454b4d"/></pattern></defs>
<path d="M100 186 C 96 140 118 104 160 102 C 204 102 226 140 220 192 C 218 216 214 234 206 246 L 116 246 C 106 232 102 212 100 186 Z" fill="#2b2523" ${S}/>
<path d="M30 420 C 34 352 68 308 126 294 L 194 294 C 252 308 286 352 290 420 Z" fill="#283642" ${S}/>
<path d="M126 294 C 116 330 122 372 146 410 L 152 420 L 100 420 C 92 380 96 330 126 294 Z" fill="#1f2c36" ${S}/>
<path d="M194 294 C 204 330 198 372 174 410 L 168 420 L 220 420 C 228 380 224 330 194 294 Z" fill="#1f2c36" ${S}/>
<path d="M108 340 l14 -6 M212 340 l-14 -6" stroke="${INK}" stroke-width="2.4"/>
<g fill="#b08a3e" stroke="${INK}" stroke-width="2"><circle cx="126" cy="376" r="5.5"/><circle cx="130" cy="408" r="5.5"/><circle cx="194" cy="376" r="5.5"/><circle cx="190" cy="408" r="5.5"/></g>
<path d="M134 226 L 134 286 C 146 298 174 298 186 286 L 186 226 Z" fill="#e8b994" ${S}/>
<path d="M120 268 C 134 294 186 294 200 268 L 206 298 C 186 318 134 318 114 298 Z" fill="#9a4a2c" ${S}/>
<path d="M130 280 C 146 292 174 292 190 280" stroke="#7a3820" stroke-width="2" fill="none"/>
<path d="M174 300 C 182 330 186 362 184 392 L 162 394 C 166 362 166 330 158 304 Z" fill="#8a4026" ${S}/>
<path d="M166 394 v10 M172 394 v10 M178 393 v10" stroke="#8a4026" stroke-width="3"/>
<ellipse cx="104" cy="184" rx="9" ry="14" fill="#e8b994" ${S}/>
<ellipse cx="216" cy="184" rx="9" ry="14" fill="#e8b994" ${S}/>
<path d="M160 108 C 202 108 216 142 214 178 C 212 212 192 240 160 242 C 128 240 108 212 106 178 C 104 142 118 108 160 108 Z" fill="#f0c6a3" ${S}/>
<path d="M110 196 C 118 224 136 240 160 242 C 140 232 122 218 110 196 Z" fill="#d8a582" opacity=".6"/>
<path d="M106 168 C 100 196 104 220 114 238 C 118 210 116 186 120 166 Z" fill="#2b2523" ${S}/>
<path d="M214 168 C 220 196 216 220 206 238 C 202 210 204 186 200 166 Z" fill="#2b2523" ${S}/>
<g ${S} fill="#2b2523" stroke-width="2.2">
  <ellipse cx="110" cy="252" rx="10" ry="12"/><ellipse cx="108" cy="274" rx="10" ry="12"/><ellipse cx="108" cy="296" rx="10" ry="12"/><ellipse cx="110" cy="318" rx="9" ry="11"/><ellipse cx="112" cy="338" rx="8" ry="10"/>
</g>
<path d="M106 350 h12" stroke="#9a4a2c" stroke-width="5" stroke-linecap="round"/>
<path d="M112 352 l-4 14 M114 352 l2 14 M117 352 l6 12" stroke="#2b2523" stroke-width="2.4"/>
<path d="M96 152 C 92 112 126 84 166 86 C 212 88 238 116 228 152 C 200 142 130 140 96 152 Z" fill="#5e6466" ${S}/>
<path d="M96 152 C 92 112 126 84 166 86 C 212 88 238 116 228 152 C 200 142 130 140 96 152 Z" fill="url(#tweed)" opacity=".8"/>
<path d="M162 88 C 160 104 160 124 164 142" stroke="#454b4d" stroke-width="2" fill="none"/>
<path d="M98 150 C 128 140 198 140 228 150 C 220 162 186 168 162 168 C 138 168 108 162 98 150 Z" fill="#4c5254" ${S}/>
<path d="M126 172 L 152 171 M168 171 L 194 172" stroke="#2b2523" stroke-width="4" stroke-linecap="round"/>
<ellipse cx="140" cy="185" rx="5" ry="4.4" fill="${INK}"/><circle cx="141.5" cy="183.6" r="1.3" fill="#fff"/>
<ellipse cx="181" cy="185" rx="5" ry="4.4" fill="${INK}"/><circle cx="182.5" cy="183.6" r="1.3" fill="#fff"/>
<path d="M130 182 C 136 178 146 178 151 182 M170 182 C 176 178 186 178 191 182" stroke="${INK}" stroke-width="2.8" fill="none"/>
<path d="M161 188 C 159 199 156 204 155 207 C 159 210 165 210 168 207" stroke="#b97a5a" stroke-width="2.3" fill="none"/>
<g fill="#b9774f" opacity=".7"><circle cx="134" cy="200" r="1.4"/><circle cx="141" cy="203" r="1.2"/><circle cx="128" cy="205" r="1.2"/><circle cx="186" cy="200" r="1.4"/><circle cx="179" cy="203" r="1.2"/><circle cx="192" cy="205" r="1.2"/></g>
<path d="M150 222 C 156 224 165 224 171 221" stroke="#8a4a3a" stroke-width="2.8" fill="none"/>`;
}

const FACES = { mara, tobias, elsie };

/** A portrait, whole (`bust`) or as a round medallion (`face`). */
export function portrait(id, { face = false } = {}) {
  const box = face ? "86 90 148 148" : "0 0 320 420";
  return `<svg viewBox="${box}" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">${FACES[id]()}</svg>`;
}

// ---- small icons ---------------------------------------------------------------------------
export const icons = {
  moon: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15.5 3.5a8.5 8.5 0 1 0 5 13.6A7 7 0 0 1 15.5 3.5Z" fill="currentColor"/></svg>`,
  seal: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.5l2 1.6 2.5-.4 1 2.3 2.3 1-.4 2.5 1.6 2-1.6 2 .4 2.5-2.3 1-1 2.3-2.5-.4-2 1.6-2-1.6-2.5.4-1-2.3-2.3-1 .4-2.5L2.5 12l1.6-2-.4-2.5 2.3-1 1-2.3 2.5.4Z" fill="currentColor"/><circle cx="12" cy="12" r="5.2" fill="none" stroke="#2a1410" stroke-width="1.4" opacity=".55"/></svg>`,
  quill: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.5 3.5c-6 .5-11 4.6-13 11.2l-1.6 5.8m1.6-5.8c3.6-.3 6.7-2.2 8.6-5.3-2 .3-3.6.1-4.8-.6 2.6-.4 5.6-2.2 9.2-5.3Z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" stroke-linecap="round"/></svg>`,
  ear: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 9.5a5.5 5.5 0 1 1 11 0c0 3-2.2 4-3.2 5.6-.9 1.5-.6 4.4-3.3 4.4-1.6 0-2.6-1-2.9-2.2M10 9.6a2.5 2.5 0 0 1 5 0c0 1.4-1.4 1.6-1.4 3" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`,
  book: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5C6.5 4.5 9.5 4.5 12 6c2.5-1.5 5.5-1.5 8-.5V19c-2.5-1-5.5-1-8 .5-2.5-1.5-5.5-1.5-8-.5V5.5ZM12 6v13.5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>`,
};
