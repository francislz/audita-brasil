"use strict";

const N = new Intl.NumberFormat("pt-BR");
const P = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
// porcentagem sem arredondar valores pequenos para zero
const pctFino = (a, b) => {
  const v = (100 * a) / b;
  return (v < 1 ? new Intl.NumberFormat("pt-BR", { maximumSignificantDigits: 2 }).format(v) : P.format(v)) + "%";
};
const fmt = (v) => (v == null ? "—" : N.format(v));
const pct = (a, b) => (b ? P.format((100 * a) / b) + "%" : "—");
const $ = (s) => document.querySelector(s);
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const TSE = "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3221/dados";
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

let R; // resumo.json
let Q0 = 24; // primeiro intervalo de 15 min das séries (06:00)
let gran = 60;
const cache = {};
let chartH, chartF, chartE;

async function getJSON(url) {
  if (!cache[url]) cache[url] = fetch(url).then((r) => {
    if (!r.ok) throw new Error(url + " " + r.status);
    return r.json();
  });
  return cache[url];
}

const hhmm = (q) => `${String(Math.floor(q / 4)).padStart(2, "0")}:${String((q % 4) * 15).padStart(2, "0")}`;
const candNome = (n) => (R.candidatos.find((c) => c.n === n) || {}).nm || n;

// ------------------------------------------------------------------ resumo

function tile(k, v, d, hero) {
  return `<div class="tile${hero ? " hero" : ""}"><div class="k">${k}</div><div class="v">${v}</div>${d ? `<div class="d">${d}</div>` : ""}</div>`;
}

function renderVeredito() {
  const b = R.brasil;
  const [c13, c22] = ["13", "22"].map((n) => R.candidatos.find((c) => c.n === n));
  const margem = Math.abs(c13.votos_ofic - c22.votos_ofic);
  const comHora = b.comp - b.semhora;
  $("#tiles").innerHTML = [
    tile("Votos após 17h · 2º turno", fmt(b.v17), `${pct(b.v17, comHora)} dos votos com horário`, true),
    tile("Votos após 17h · 1º turno", fmt(b.v17_t1), "mesmas urnas, sem prorrogação"),
    tile("Votos após 19h · 2º turno", fmt(b.v19), "depois do novo horário"),
    tile("Diferença entre os candidatos", fmt(margem), "resultado oficial do TSE"),
  ].join("");
  const vezes = b.v17 ? margem / b.v17 : null;
  $("#veredito-texto").innerHTML =
    `Das ${fmt(comHora)} pessoas cujo voto tem horário registrado no log, <strong>${fmt(b.v17)}</strong> votaram depois das 17h (horário de Brasília). ` +
    `Para que a prorrogação tivesse dado 10 milhões de votos a um candidato, seria preciso que pelo menos 10 milhões de pessoas tivessem votado nesse período. ` +
    `A prorrogação até as 19h só aconteceu em ${fmt(b.secp)} das ${fmt(b.nsec)} seções (veja abaixo). ` +
    (vezes ? `Mesmo que <em>todos</em> os votos após as 17h tivessem ido para um único candidato, eles somariam ${vezes >= 1 ? `${pctFino(b.v17, margem)} da diferença final entre os dois` : "mais do que a diferença final"}.` : "");
  const cob = Object.values(R.status).reduce((a, v) => a + v, 0);
  if (cob < R.secoes_config) {
    const el = $("#cobertura");
    el.hidden = false;
    el.innerHTML = `<strong>Dados parciais:</strong> ${fmt(cob)} de ${fmt(R.secoes_config)} seções processadas até agora (${pct(cob, R.secoes_config)}). Os números serão atualizados quando o download terminar.`;
  }
}

function renderCand() {
  const b = R.brasil;
  const tot = b.comp || 1;
  const cards = R.candidatos.map((c) => {
    const est = b.est17[c.n] || 0, max = b.max17[c.n] || 0, bu = b.votos[c.n] || 0;
    const cor = c.n === "13" ? "var(--lula)" : "var(--flavio)";
    return `<div class="cand-card">
      <h3><span class="dot" style="background:${cor}"></span>${esc(c.nm)} <span class="muted">(${esc(c.partido)})</span></h3>
      <div class="muted">Resultado oficial: ${fmt(c.votos_ofic)} votos (${esc(c.pct_ofic)}% dos válidos)</div>
      <div class="cand-linha"><span>Estimativa proporcional após 17h</span><b>${fmt(est)}</b></div>
      <div class="barra" title="${pct(est, b.v17)} dos votos após 17h"><span style="width:${b.v17 ? (100 * est) / b.v17 : 0}%;background:${cor}"></span></div>
      <div class="cand-linha"><span>Teto: máximo possível após 17h</span><b>${fmt(max)}</b></div>
      <div class="barra" title="${pct(max, b.v17)} dos votos após 17h"><span style="width:${b.v17 ? (100 * max) / b.v17 : 0}%;background:${cor}"></span></div>
      <div class="muted" style="margin-top:8px">Votos somados dos BUs processados: ${fmt(bu)} (${pct(bu, tot)} do comparecimento)</div>
    </div>`;
  });
  const e = R.eco, eTot = (o) => Object.values(o).reduce((a, b) => a + b, 0);
  const ecoTxt = e && eTot(e.com) ? `<p class="sub" style="margin-top:16px">Para comparação: nas seções que tiveram algum voto após as 17h, ${esc(candNome("13"))} teve ${pct(e.com["13"] || 0, eTot(e.com))} e ${esc(candNome("22"))} ${pct(e.com["22"] || 0, eTot(e.com))} dos votos da seção inteira; nas demais seções, ${pct(e.sem["13"] || 0, eTot(e.sem))} e ${pct(e.sem["22"] || 0, eTot(e.sem))}. Essa diferença reflete principalmente <em>onde</em> há filas (cidades grandes, por exemplo), não o voto de quem chegou tarde.</p>` : "";
  $("#cand").innerHTML = `<div class="cand-grid">${cards.join("")}</div>
    <p class="muted" style="margin-top:12px">Barras: fração dos ${fmt(b.v17)} votos registrados após 17h. A estimativa supõe que quem votou tarde votou como o resto da sua seção; o teto é um limite matemático, não uma estimativa.</p>${ecoTxt}`;
}

function sortable(table, rows, cols, initial) {
  let key = initial, dir = -1;
  const draw = () => {
    const rs = [...rows].sort((a, b) => {
      const x = cols[key].v(a), y = cols[key].v(b);
      return (typeof x === "string" ? x.localeCompare(y) : x - y) * dir;
    });
    table.innerHTML = `<thead><tr>${cols.map((c, i) => `<th scope="col" data-i="${i}"${i === key ? ` aria-sort="${dir < 0 ? "descending" : "ascending"}"` : ""}>${c.h}${i === key ? (dir < 0 ? " ▼" : " ▲") : ""}</th>`).join("")}</tr></thead>
      <tbody>${rs.map((r) => `<tr>${cols.map((c) => `<td>${c.f ? c.f(r) : esc(c.v(r))}</td>`).join("")}</tr>`).join("")}</tbody>`;
    table.querySelectorAll("th").forEach((th) => th.addEventListener("click", () => {
      const i = +th.dataset.i;
      dir = i === key ? -dir : -1;
      key = i;
      draw();
    }));
  };
  draw();
}

function renderUF() {
  const rows = Object.entries(R.ufs).map(([uf, a]) => ({ uf, ...a }));
  sortable($("#t-uf"), rows, [
    { h: "Estado", v: (r) => r.nm },
    { h: "Comparecimento", v: (r) => r.comp, f: (r) => fmt(r.comp) },
    { h: candNome("13"), v: (r) => (r.votos["13"] || 0) / (r.comp || 1), f: (r) => pct(r.votos["13"] || 0, r.comp) },
    { h: candNome("22"), v: (r) => (r.votos["22"] || 0) / (r.comp || 1), f: (r) => pct(r.votos["22"] || 0, r.comp) },
    { h: "Após 17h (2º t.)", v: (r) => r.v17, f: (r) => fmt(r.v17) },
    { h: "Após 17h (1º t.)", v: (r) => r.v17_t1, f: (r) => fmt(r.v17_t1) },
    { h: "Após 19h", v: (r) => r.v19, f: (r) => fmt(r.v19) },
    { h: "Seções c/ voto após 17h", v: (r) => r.sec17, f: (r) => `${fmt(r.sec17)} de ${fmt(r.nsec)}` },
  ], 4);
}

function renderTardias() {
  sortable($("#t-tardias"), R.tardias, [
    { h: "Local", v: (r) => `${r.nm} (${r.uf.toUpperCase()})` },
    { h: "Zona", v: (r) => r.zona },
    { h: "Seção", v: (r) => r.secao },
    { h: "Após 17h", v: (r) => r.v17, f: (r) => fmt(r.v17) },
    { h: "Após 19h", v: (r) => r.v19, f: (r) => fmt(r.v19) },
    { h: "Após 17h no 1º t.", v: (r) => r.v17_t1, f: (r) => fmt(r.v17_t1) },
    { h: "Último voto", v: (r) => r.ultimo || "" },
    { h: "Arquivos TSE", v: () => "", f: (r) => `<a href="${TSE}/${r.uf}/${r.mun}/${r.zona}/${r.secao}/p003221-${r.uf}-m${r.mun}-z${r.zona}-s${r.secao}-aux.json" rel="noopener">abrir</a>` },
  ], 3);
}

function renderInteg() {
  const b = R.brasil, x = R.exterior;
  const ok = (c, t) => `<div class="check"><span class="ic ${c ? "ok" : "bad"}" aria-label="${c ? "ok" : "atenção"}">${c ? "✓" : "!"}</span><div>${t}</div></div>`;
  const nErr = Object.values(R.erros).reduce((a, v) => a + v, 0);
  const sobra = R.secoes_config - b.nsec - x.nsec;
  const naoInst = R.status["Nao instalada"] || 0;
  $("#integ").innerHTML = [
    ok(b.rdv_div === 0, `<strong>RDV × Boletim de Urna:</strong> em ${fmt(b.rdv_ok)} seções a lista de votos (RDV) bate exatamente com o resultado do BU para Presidente; ${fmt(b.rdv_div)} divergem.`),
    ok(b.log_div <= b.nsec * 0.01, `<strong>Log × Boletim de Urna:</strong> em ${fmt(b.log_ok)} seções o número de votos no log é igual ao comparecimento do BU; ${fmt(b.log_div)} diferem (em geral urnas substituídas durante o dia, cujo log publicado cobre só a urna de reserva), totalizando ${fmt(b.semhora)} votos sem horário.`),
    ok(true, `<strong>Total processado:</strong> ${fmt(b.nsec + x.nsec)} seções (${fmt(b.nsec)} no Brasil e ${fmt(x.nsec)} no exterior) de ${fmt(R.secoes_config)} listadas pelo TSE. Comparecimento somado: ${fmt(b.comp + x.comp)}.` +
      (sobra ? ` As ${fmt(sobra)} restantes não têm boletim eletrônico: ${fmt(naoInst)} não foram instaladas e ${fmt(sobra - naoInst)} votaram em cédula de papel.` : "")),
    ok(nErr === 0, `<strong>Arquivos com erro de leitura:</strong> ${fmt(nErr)}.`),
    ok(true, `<strong>Exterior:</strong> ${fmt(x.comp)} votos em ${fmt(x.nsec)} seções; ${fmt(x.v17)} depois das 17h no horário local de cada país.`),
  ].join("");
  $("#rodape").innerHTML = `Dados do TSE extraídos em ${esc(R.gerado_em.replace("T", " ").replace("+00:00", " UTC"))}. Página sem vínculo com o TSE ou com qualquer candidato ou partido.`;
}

function renderProrr() {
  const b = R.brasil, P = R.prorrogacao;
  $("#tiles-prorr").innerHTML = [
    tile("Seções prorrogadas", fmt(b.secp), `de ${fmt(b.nsec)} (${pctFino(b.secp, b.nsec)})`, true),
    tile("Municípios", fmt(P.length), "com ao menos uma seção prorrogada"),
    tile("Eleitores nessas seções", fmt(b.compp), `${pctFino(b.compp, b.comp)} do comparecimento`),
    tile("Votos após 17h nelas", fmt(b.v17p), `de ${fmt(b.v17)} no país`),
  ].join("");
  sortable($("#t-prorr"), P, [
    { h: "Município", v: (r) => `${r.nm} (${r.uf.toUpperCase()})` },
    { h: "Seções prorrogadas", v: (r) => r.secp, f: (r) => `${fmt(r.secp)} de ${fmt(r.nsec)}` },
    { h: "Eleitores nelas", v: (r) => r.compp, f: (r) => fmt(r.compp) },
    { h: "Votos após 17h nelas", v: (r) => r.v17p, f: (r) => fmt(r.v17p) },
  ], 1);
}

function renderEnc() {
  const q0 = 16 * 4 + 3, q1 = 20 * 4 + 2;
  const labels = [], a2 = [], a1 = [];
  for (let q = q0; q < q1; q++) {
    labels.push(hhmm(q));
    a2.push(R.enc2[q] || 0);
    a1.push(R.enc1[q] || 0);
  }
  chartE = barras($("#c-enc"), labels, a2, a1, q0, "Encerradas entre", "urnas", true);
}

// ------------------------------------------------------------------ gráfico por horário

const bandPlugin = {
  id: "band",
  beforeDatasetsDraw(chart, _a, opts) {
    const { ctx, chartArea: a, scales: { x } } = chart;
    const labels = chart.data.labels;
    const i0 = labels.indexOf(opts.from), i1 = labels.indexOf(opts.to);
    if (i0 < 0) return;
    const step = x.getPixelForValue(1) - x.getPixelForValue(0);
    const x0 = x.getPixelForValue(i0) - step / 2;
    const x1 = i1 < 0 ? a.right : x.getPixelForValue(i1) - step / 2;
    ctx.save();
    ctx.fillStyle = css("--band");
    ctx.fillRect(x0, a.top, x1 - x0, a.bottom - a.top);
    ctx.restore();
  },
};

function agrupa(s, g) {
  if (g === 15) return s.slice();
  const out = [];
  for (let i = 0; i < s.length; i += 4) out.push(s.slice(i, i + 4).reduce((a, b) => a + b, 0));
  return out;
}

function desenhaHorario(s2, s1, g, titulo) {
  const labels = [];
  const n = s2.length;
  for (let i = 0; i < n; i++) labels.push(g === 15 ? hhmm(Q0 + i) : hhmm(Q0 + i * 4).slice(0, 2) + "h");
  const from = g === 15 ? "17:00" : "17h", to = g === 15 ? "19:00" : "19h";
  const grid = css("--grid"), muted = css("--text-muted");
  const data = {
    labels,
    datasets: [
      { label: "2º turno", data: s2, borderColor: css("--t2"), backgroundColor: css("--t2"), borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, tension: 0.25 },
      { label: "1º turno", data: s1, borderColor: css("--t1"), backgroundColor: css("--t1"), borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, tension: 0.25 },
    ],
  };
  const options = {
    responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      band: { from, to },
      tooltip: {
        callbacks: {
          title: (it) => (g === 15 ? `${it[0].label}–${hhmm(Q0 + it[0].dataIndex + 1)}` : `${it[0].label} às ${String(+it[0].label.slice(0, 2) + 1).padStart(2, "0")}h`),
          label: (it) => ` ${it.dataset.label}: ${fmt(it.raw)} votos`,
        },
      },
    },
    scales: {
      x: { grid: { display: false }, ticks: { color: muted, maxRotation: 0, autoSkip: true, autoSkipPadding: 12 }, border: { color: grid } },
      y: { beginAtZero: true, grid: { color: grid }, ticks: { color: muted, callback: (v) => N.format(v) }, border: { display: false } },
    },
  };
  if (chartH) { chartH.data = data; chartH.options = options; chartH.update(); }
  else chartH = new Chart($("#c-horario"), { type: "line", data, options, plugins: [bandPlugin] });
  $("#cap-horario").textContent = titulo;
  $("#tab-horario").innerHTML = `<div class="tabela-scroll"><table class="tabela"><thead><tr><th>Horário</th><th>2º turno</th><th>1º turno</th></tr></thead><tbody>${labels.map((l, i) => `<tr><td>${l}</td><td>${fmt(s2[i])}</td><td>${fmt(s1[i])}</td></tr>`).join("")}</tbody></table></div>`;
}

function painel(titulo, a, extra = "") {
  const comp = a.comp;
  $("#painel").innerHTML = `<h3>${esc(titulo)}</h3><dl>
    <dt>Seções</dt><dd>${fmt(a.nsec)}</dd>
    <dt>Comparecimento</dt><dd>${fmt(comp)}</dd>
    <dt><span class="dot" style="background:var(--lula)"></span>${esc(candNome("13"))}</dt><dd>${fmt(a.votos["13"] || 0)} · ${pct(a.votos["13"] || 0, comp)}</dd>
    <dt><span class="dot" style="background:var(--flavio)"></span>${esc(candNome("22"))}</dt><dd>${fmt(a.votos["22"] || 0)} · ${pct(a.votos["22"] || 0, comp)}</dd>
    <dt>Brancos / nulos</dt><dd>${fmt(a.votos.branco || 0)} / ${fmt(a.votos.nulo || 0)}</dd>
    <div class="sep"></div>
    <dt>Votos após 17h (2º t.)</dt><dd>${fmt(a.v17)}</dd>
    <dt>Votos após 19h (2º t.)</dt><dd>${fmt(a.v19)}</dd>
    <dt>Votos após 17h (1º t.)</dt><dd>${fmt(a.v17_t1)}</dd>
    <dt>Votos sem horário</dt><dd>${fmt(a.semhora)}</dd>
    ${a.secp != null ? `<dt>Seções prorrogadas</dt><dd>${fmt(a.secp)}</dd>` : ""}
  </dl>${extra}`;
}

// estado dos filtros
const F = { uf: "", mun: "", zona: "", sec: "" };
let ufData = null, secData = null;

function opts(sel, items, todos) {
  sel.innerHTML = `<option value="">${todos}</option>` + items.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join("");
}

async function atualiza() {
  const g = gran;
  if (!F.uf) {
    painel("Brasil", R.brasil);
    return desenhaHorario(agrupa(R.brasil.s2, g), agrupa(R.brasil.s1, g), g, "Brasil, exceto exterior. Horário de Brasília.");
  }
  ufData = await getJSON(`data/uf/${F.uf}.json`);
  if (!F.mun) {
    painel(ufData.nm, ufData);
    return desenhaHorario(agrupa(ufData.s2, g), agrupa(ufData.s1, g), g, `${ufData.nm}. Horário de Brasília.`);
  }
  const m = ufData.municipios.find((x) => x.cd === F.mun);
  const fusoTxt = m.fuso ? ` O horário local de ${m.nm} é ${m.fuso}h atrás de Brasília.` : "";
  if (!F.zona) {
    painel(`${m.nm} (${F.uf.toUpperCase()})`, m);
    return desenhaHorario(agrupa(m.s2, g), agrupa(m.s1, g), g, `${m.nm}. Horário de Brasília.${fusoTxt}`);
  }
  const z = m.zonas[F.zona];
  if (!F.sec) {
    painel(`${m.nm} · zona ${F.zona}`, z);
    return desenhaHorario(agrupa(z.s2, g), agrupa(z.s1, g), g, `${m.nm}, zona ${F.zona}. Horário de Brasília.${fusoTxt}`);
  }
  const s = secData.find((r) => r[0] === F.zona && r[1] === F.sec);
  const a = { nsec: 1, comp: s[3], votos: { "13": s[4], "22": s[5], branco: s[6], nulo: s[7] }, v17: s[8], v19: s[9], v17_t1: s[10], semhora: Math.max(0, s[15] ?? s[3]) };
  const link = `${TSE}/${F.uf}/${F.mun}/${F.zona}/${F.sec}/p003221-${F.uf}-m${F.mun}-z${F.zona}-s${F.sec}-aux.json`;
  const extra = `<p class="muted" style="margin-top:12px">Último voto: ${s[11] || "—"} · RDV ${s[14] === true ? "confere com o BU ✓" : s[14] === false ? "diverge do BU !" : "indisponível"}<br><a href="${link}" rel="noopener">Arquivos desta seção no TSE</a></p>`;
  painel(`${m.nm} · zona ${F.zona} · seção ${F.sec}`, a, extra);
  // seções têm só séries por hora (06h–20h)
  desenhaHorario(s[12], s[13], 60, `Seção ${F.sec}, zona ${F.zona}, ${m.nm}. Por hora, horário de Brasília.${fusoTxt}`);
}

function bindFiltros() {
  const sUF = $("#f-uf"), sMun = $("#f-mun"), sZona = $("#f-zona"), sSec = $("#f-sec");
  opts(sUF, Object.entries(R.ufs).sort((a, b) => a[1].nm.localeCompare(b[1].nm)).map(([uf, a]) => [uf, a.nm]), "Brasil (todos)");
  const reset = (...sels) => sels.forEach((s) => { opts(s, [], "Todas"); s.disabled = true; });
  sUF.addEventListener("change", async () => {
    Object.assign(F, { uf: sUF.value, mun: "", zona: "", sec: "" });
    reset(sMun, sZona, sSec);
    if (F.uf) {
      ufData = await getJSON(`data/uf/${F.uf}.json`);
      opts(sMun, ufData.municipios.map((m) => [m.cd, m.nm]), "Todas");
      sMun.disabled = false;
    }
    atualiza();
  });
  sMun.addEventListener("change", async () => {
    Object.assign(F, { mun: sMun.value, zona: "", sec: "" });
    reset(sZona, sSec);
    if (F.mun) {
      const m = ufData.municipios.find((x) => x.cd === F.mun);
      opts(sZona, Object.keys(m.zonas).map((z) => [z, `Zona ${z}`]), "Todas");
      sZona.disabled = false;
      secData = await getJSON(`data/secoes/${F.uf}/${F.mun}.json`);
    }
    atualiza();
  });
  sZona.addEventListener("change", () => {
    Object.assign(F, { zona: sZona.value, sec: "" });
    reset(sSec);
    if (F.zona) {
      opts(sSec, secData.filter((r) => r[0] === F.zona).map((r) => [r[1], `Seção ${r[1]}`]).sort(), "Todas");
      sSec.disabled = false;
    }
    atualiza();
  });
  sSec.addEventListener("change", () => { F.sec = sSec.value; atualiza(); });
  document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
    gran = +b.dataset.g;
    document.querySelectorAll(".seg button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    atualiza();
  }));
}

// ------------------------------------------------------------------ último voto

function barras(canvas, labels, a2, a1, q0, titulo, unidade, log) {
  const grid = css("--grid"), muted = css("--text-muted");
  return new Chart(canvas, {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "2º turno", data: a2, backgroundColor: css("--t2"), borderRadius: 4, borderSkipped: "bottom", categoryPercentage: 0.8, barPercentage: 0.9 },
        { label: "1º turno", data: a1, backgroundColor: css("--t1"), borderRadius: 4, borderSkipped: "bottom", categoryPercentage: 0.8, barPercentage: 0.9 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { title: (it) => `${titulo} ${it[0].label} e ${hhmm(q0 + it[0].dataIndex + 1)}`, label: (it) => ` ${it.dataset.label}: ${fmt(it.raw)} ${unidade}` } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: muted, maxRotation: 0, autoSkipPadding: 10 }, border: { color: grid } },
        y: log
          ? { type: "logarithmic", min: 1, grid: { color: grid }, ticks: { color: muted, callback: (v) => ([1, 10, 100, 1e3, 1e4, 1e5, 1e6].includes(v) ? N.format(v) : "") }, border: { display: false } }
          : { beginAtZero: true, grid: { color: grid }, ticks: { color: muted, callback: (v) => N.format(v) }, border: { display: false } },
      },
    },
  });
}

function renderFim() {
  const q0 = 16 * 4, q1 = 20 * 4;
  const labels = [], a2 = [], a1 = [];
  for (let q = q0; q < q1; q++) {
    labels.push(hhmm(q));
    a2.push(R.fim2[q] || 0);
    a1.push(R.fim1[q] || 0);
  }
  chartF = barras($("#c-fim"), labels, a2, a1, q0, "Último voto entre", "seções");
}

// ------------------------------------------------------------------ init

(async function init() {
  R = await getJSON("data/resumo.json");
  Q0 = R.janela.q0;
  renderVeredito();
  renderProrr();
  renderCand();
  renderUF();
  renderTardias();
  renderInteg();
  bindFiltros();
  await atualiza();
  renderFim();
  renderEnc();
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    chartF.destroy();
    renderFim();
    chartE.destroy();
    renderEnc();
    chartH.destroy();
    chartH = null;
    atualiza();
  });
})();
