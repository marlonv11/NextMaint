(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const TH = { cpu: [75, 90], ram: [75, 90], disco: [75, 90], temp: [65, 80] };
  const level = (k, v) => v >= TH[k][1] ? 'alto' : v >= TH[k][0] ? 'medio' : 'bajo';
  const LABEL = { bajo: 'Bajo', medio: 'Medio', alto: 'Alto' };
  const safeR = r => (r in LABEL ? r : 'bajo');
  const CIRC = 2 * Math.PI * 42;
  const POLL_MS = 2000, HIST_MAX = 30;
  const NOMBRE_DEMO = 'PC-DEMO';
  const ago = s => s == null ? 'sin datos' : s < 60 ? `hace ${s} s` : s < 3600 ? `hace ${Math.floor(s / 60)} min`
    : s < 86400 ? `hace ${Math.floor(s / 3600)} h` : `hace ${Math.floor(s / 86400)} d`;

  const st = { tiles: new Map(), hist: new Map(), seenAlerts: null, alertSig: '', sel: null, trigger: null,
               lastChange: Date.now(), ok: false, first: true, demo: false };

  const j = async (url, opts) => { const r = await fetch(url, opts); if (!r.ok) throw new Error(r.status); return r.json(); };

  /* Números que cuentan hasta su valor */
  function tween(el, to, dec = 0) {
    if (to == null || Number.isNaN(to)) { el.textContent = '–'; delete el.dataset.v; return; }
    const from = el.dataset.v === undefined ? to : parseFloat(el.dataset.v);
    el.dataset.v = to;
    cancelAnimationFrame(el._raf);
    if (reduce || from === to) { el.textContent = to.toFixed(dec); return; }
    const t0 = performance.now(), d = 800;
    const step = t => {
      const p = clamp((t - t0) / d, 0, 1), e = 1 - Math.pow(1 - p, 3);
      el.textContent = (from + (to - from) * e).toFixed(dec);
      if (p < 1) el._raf = requestAnimationFrame(step);
    };
    el._raf = requestAnimationFrame(step);
  }

  /* Anillos */
  const ringHTML = () => `<svg class="ring" viewBox="0 0 100 100" aria-hidden="true"><circle class="trk" cx="50" cy="50" r="42"/><circle class="arc" cx="50" cy="50" r="42" transform="rotate(-90 50 50)" style="stroke-dasharray:${CIRC.toFixed(1)};stroke-dashoffset:${CIRC.toFixed(1)}"/></svg>`;
  function setRing(svg, pct, lvl) {
    const a = $('.arc', svg);
    a.style.strokeDashoffset = (CIRC * (1 - clamp(pct ?? 0, 0, 100) / 100)).toFixed(1);
    a.style.stroke = `var(--${lvl})`;
  }

  /* Línea pequeña dentro de cada pantalla */
  function spark(tile, vals) {
    if (vals.length < 2) return;
    const W = 200, H = 34, n = vals.length;
    // Escala local: así se notan las variaciones aunque el valor casi no cambie
    const lo = Math.min(...vals), hi = Math.max(...vals), span = Math.max(hi - lo, 14), base = (lo + hi) / 2 - span / 2;
    const d = 'M' + vals.map((v, i) => `${(W * i / (n - 1)).toFixed(1)} ${(30 - 26 * (v - base) / span).toFixed(1)}`).join('L');
    $('.sl', tile).setAttribute('d', d);
    $('.sa', tile).setAttribute('d', `${d}L${W} ${H}L0 ${H}Z`);
  }

  /* Equipo en el mapa */
  function makeTile(name, i) {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'pc enter'; b.dataset.name = name; b.style.setProperty('--i', i);
    b.innerHTML = `
      <span class="screen">
        <span class="row"><span class="name"></span><span class="tag"><svg class="ic" aria-hidden="true"><use href="#i-bajo"/></svg><span class="tagtxt"></span></span></span>
        <span class="mid">
          <span class="ringwrap">${ringHTML()}<span class="ringtxt"><small>CPU</small><b class="v-cpu" data-v="0">0</b></span></span>
          <span class="stats">
            <span class="stat" data-k="ram"><span>RAM</span><span class="bar"><i></i></span><span class="num"><b class="nv" data-v="0">0</b>%</span></span>
            <span class="stat" data-k="disco"><span>Disco</span><span class="bar"><i></i></span><span class="num"><b class="nv" data-v="0">0</b>%</span></span>
            <span class="stat temp" data-level="bajo"><b class="v-temp" data-v="0">0</b><span>°C</span><span class="est" hidden>estimada</span></span>
          </span>
        </span>
        <svg class="spark" viewBox="0 0 200 34" preserveAspectRatio="none" aria-hidden="true"><path class="sa"/><path class="sl"/></svg>
        <span class="ago"></span>
      </span>
      <span class="stand"></span><span class="base"></span>`;
    $('.name', b).textContent = name;
    b.addEventListener('animationend', () => b.classList.remove('enter'), { once: true });
    b.addEventListener('click', () => openDrawer(name, b));
    return b;
  }

  function updateTile(tile, e) {
    // Un equipo "sin conexión" conserva sus últimos valores, pero se muestra apagado y sin nivel de riesgo.
    const on = !!e.conectado, risk = on ? safeR(e.nivel) : 'off', t = e.temperatura, est = !!e.temp_estimada;
    tile.dataset.risk = safeR(e.nivel);
    tile.dataset.conn = on ? 'on' : 'off';
    tile.style.setProperty('--heat', on ? clamp(((t ?? 40) - 40) / 50, 0, 1).toFixed(2) : '0');
    $('.tagtxt', tile).textContent = on ? 'Riesgo ' + LABEL[risk].toLowerCase() : 'Sin conexión';
    $('.tag use', tile).setAttribute('href', '#i-' + risk);
    $('.ago', tile).textContent = on ? '' : 'Sin datos ' + ago(e.segundos_sin_datos);
    const cpu = e.cpu ?? 0;
    setRing($('.ring', tile), cpu, on ? level('cpu', cpu) : 'off');
    tween($('.v-cpu', tile), e.cpu);
    for (const k of ['ram', 'disco']) {
      const s = $(`.stat[data-k="${k}"]`, tile), v = e[k] ?? 0, bar = $('i', s);
      bar.style.width = clamp(v, 0, 100) + '%';
      bar.style.background = `var(--${on ? level(k, v) : 'off'})`;
      tween($('.nv', s), e[k]);
    }
    tween($('.v-temp', tile), t);
    $('.est', tile).hidden = !est;
    // La temperatura estimada no se resalta como alerta: no es una medición
    $('.stat.temp', tile).dataset.level = on && !est ? level('temp', t ?? 0) : 'bajo';
    tile.setAttribute('aria-label', on
      ? `${e.nombre}, riesgo ${LABEL[risk].toLowerCase()}, CPU ${e.cpu ?? 'sin dato'} por ciento, temperatura ${est ? 'estimada ' : ''}${t ?? 'sin dato'} grados. Abrir detalle`
      : `${e.nombre}, sin conexión, sin datos ${ago(e.segundos_sin_datos)}. Abrir detalle`);
  }

  function trackHistory(e) {
    const h = st.hist.get(e.nombre) || { cpu: [], temp: [], last: '' };
    st.hist.set(e.nombre, h);
    if (e.cpu == null) return h;
    const key = e.fecha + '|' + e.cpu + '|' + e.temperatura;
    if (h.last !== key) {
      h.last = key; h.cpu.push(e.cpu); h.temp.push(e.temperatura);
      if (h.cpu.length > HIST_MAX) { h.cpu.shift(); h.temp.shift(); }
      st.lastChange = Date.now();
    }
    return h;
  }

  async function seedHistory(eq) {
    await Promise.all(eq.filter(e => e.cpu != null).map(async e => {
      try {
        const d = await j('/api/equipos/' + encodeURIComponent(e.nombre));
        const hist = d.historial.slice(-HIST_MAX);
        st.hist.set(e.nombre, { cpu: hist.map(p => p.cpu), temp: hist.map(p => p.temperatura),
                                last: e.fecha + '|' + e.cpu + '|' + e.temperatura });
      } catch { /* se llena solo con las siguientes mediciones */ }
    }));
  }

  function renderFloor(eq) {
    const floor = $('#floor');
    $('#empty').hidden = eq.length > 0;
    let fresh = false;
    eq.forEach((e, i) => {
      let tile = st.tiles.get(e.nombre);
      if (!tile) { tile = makeTile(e.nombre, i); st.tiles.set(e.nombre, tile); fresh = true; if (!st.first) tile.classList.remove('enter'); }
      if (floor.children[i] !== tile) floor.insertBefore(tile, floor.children[i] || null);
    });
    if (fresh) void floor.offsetWidth;
    eq.forEach(e => { const h = trackHistory(e); const tile = st.tiles.get(e.nombre); updateTile(tile, e); spark(tile, h.cpu); });
    // Equipos que desaparecieron (por ejemplo, al quitar la demo)
    const vivos = new Set(eq.map(e => e.nombre));
    for (const [n, t] of st.tiles) if (!vivos.has(n)) { t.remove(); st.tiles.delete(n); st.hist.delete(n); }
    if (st.sel && !vivos.has(st.sel)) closeDrawer();
  }

  /* Resumen */
  function renderSummary(eq) {
    // Los equipos sin conexión no cuentan en el riesgo: se muestran aparte.
    const c = { bajo: 0, medio: 0, alto: 0, off: 0 };
    eq.forEach(e => c[e.conectado ? safeR(e.nivel) : 'off']++);
    for (const r of ['bajo', 'medio', 'alto', 'off']) {
      const seg = $('#seg-' + r);
      seg.style.flexGrow = c[r]; seg.classList.toggle('on', c[r] > 0);
      tween($('#n-' + r), c[r]);
    }
    const names = r => eq.filter(e => (r === 'off' ? !e.conectado : e.conectado && e.nivel === r)).map(e => e.nombre).join(', ');
    const conectados = eq.length - c.off;
    let worst = 'bajo', txt;
    if (!eq.length) txt = 'Esperando datos de los equipos…';
    else if (!conectados) { worst = 'off'; txt = 'Ningún equipo está enviando datos.'; }
    else if (c.alto) { worst = 'alto'; txt = (c.alto === 1 ? 'Requiere mantenimiento: ' : 'Requieren mantenimiento: ') + names('alto') + '.'; }
    else if (c.medio) { worst = 'medio'; txt = 'Conviene revisar: ' + names('medio') + '.'; }
    else txt = c.off ? 'Los equipos conectados funcionan con normalidad.' : 'Todos los equipos funcionan con normalidad.';
    if (c.off && conectados) txt += ` Sin conexión: ${names('off')}.`;
    $('#sumTxt').textContent = txt;
    $('#sumLine').dataset.risk = worst;
    $('#sumIc').setAttribute('href', '#i-' + worst);
    $('#stack').setAttribute('aria-label', `${c.bajo} equipos en riesgo bajo, ${c.medio} en medio, ${c.alto} en alto, ${c.off} sin conexión`);
  }

  /* Alertas */
  function alertItem(a, isNew) {
    const r = safeR(a.riesgo), done = a.estado !== 'activa';
    const li = document.createElement('li');
    li.className = 'al' + (isNew ? ' is-new' : '') + (done ? ' done' : '');
    li.dataset.risk = r;
    li.innerHTML = `<svg class="ic" aria-hidden="true"><use href="#i-${r}"/></svg>
      <div><div class="al-head"><button type="button" class="al-name"></button><time></time></div><p class="al-msg"></p><div class="al-act"></div></div>`;
    $('.al-name', li).textContent = a.equipo;
    $('.al-name', li).addEventListener('click', e => openDrawer(a.equipo, e.currentTarget));
    $('time', li).textContent = (a.fecha || '').slice(11, 16);
    $('.al-msg', li).textContent = a.mensaje;
    $('.al-act', li).replaceChildren();
    if (!done) {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'btn'; b.textContent = 'Marcar como resuelta';
      b.addEventListener('click', async () => {
        b.disabled = true;
        try { await j(`/api/alertas/${a.id}/resolver`, { method: 'POST' }); await poll(true); } catch { b.disabled = false; }
      });
      $('.al-act', li).append(b);
    } else { const s = document.createElement('span'); s.className = 'muted'; s.textContent = 'Resuelta'; $('.al-act', li).append(s); }
    return li;
  }

  function renderAlerts(list) {
    const sig = list.map(a => a.id + a.estado).join(',');
    if (sig === st.alertSig) return;
    st.alertSig = sig;
    const act = list.filter(a => a.estado === 'activa'), done = list.filter(a => a.estado !== 'activa');
    const known = st.seenAlerts;
    $('#alerts').replaceChildren(...act.map(a => alertItem(a, known && !known.has(a.id))));
    $('#noAlerts').hidden = act.length > 0;
    $('#resolvedBox').hidden = done.length === 0;
    $('#doneCount').textContent = done.length;
    $('#done').replaceChildren(...done.map(a => alertItem(a, false)));
    st.seenAlerts = new Set(list.map(a => a.id));
  }

  /* Detalle del equipo */
  const drawer = $('#drawer'), scrim = $('#scrim');
  $$('.g .ringwrap', drawer).forEach(w => { w.innerHTML = ringHTML() + '<span class="ringtxt"><b><span class="gv" data-v="0">0</span>%</b></span>'; });

  function chart(id, vals, o) {
    if (vals.length < 2) return '<p class="muted">Reuniendo mediciones…</p>';
    const W = 480, H = 160, pl = 34, pr = 8, pt = 12, pb = 20, n = vals.length;
    const x = i => pl + (W - pl - pr) * i / (n - 1);
    const y = v => pt + (H - pt - pb) * (1 - (clamp(v, o.min, o.max) - o.min) / (o.max - o.min));
    const line = 'M' + vals.map((v, i) => `${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join('L');
    const area = `${line}L${x(n - 1).toFixed(1)} ${H - pb}L${x(0).toFixed(1)} ${H - pb}Z`;
    const mid = (o.min + o.max) / 2, last = vals[n - 1], lx = x(n - 1), ly = y(last);
    const grid = [o.min, mid, o.max].map(v => `<line x1="${pl}" x2="${W - pr}" y1="${y(v)}" y2="${y(v)}" stroke="rgba(255,255,255,.09)"/><text x="${pl - 8}" y="${y(v) + 4}" text-anchor="end">${v}</text>`).join('');
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${o.label}: último valor ${last} ${o.unit}">
      <defs><linearGradient id="g-${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" style="stop-color:var(--${o.lvl});stop-opacity:.5"/><stop offset="1" style="stop-color:var(--${o.lvl});stop-opacity:0"/></linearGradient></defs>
      ${grid}
      ${o.thr == null ? '' : `<line x1="${pl}" x2="${W - pr}" y1="${y(o.thr)}" y2="${y(o.thr)}" stroke="var(--alto)" stroke-width="1.4" stroke-dasharray="5 5"/>
      <text x="${pl + 6}" y="${last >= o.thr ? y(o.thr) + 16 : y(o.thr) - 6}" style="fill:var(--text)">Riesgo alto desde ${o.thr} ${o.unit}</text>`}
      <path d="${area}" fill="url(#g-${id})"/>
      <path d="${line}" fill="none" style="stroke:var(--${o.lvl})" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/>
      <circle class="dot-ping" cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="4.5" style="fill:var(--${o.lvl})"/>
      <circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="5" style="fill:var(--${o.lvl})" stroke="#171132" stroke-width="2"/>
    </svg>`;
  }

  function paintDrawer(name, d) {
    const a = d.actual, on = !!a.conectado, r = on ? safeR(a.nivel) : 'off', est = !!a.temp_estimada;
    $('#dTitle').textContent = name;
    $('#dTag').dataset.risk = r;
    $('#dTag use').setAttribute('href', '#i-' + r);
    $('#dTagTxt').textContent = on ? 'Riesgo ' + LABEL[r].toLowerCase() : 'Sin conexión';
    $('#dAdvice').dataset.risk = r;
    const ul = $('#dRec'); ul.replaceChildren();
    const add = t => { const li = document.createElement('li'); li.textContent = t; ul.append(li); };
    if (!on) {
      $('#dAdvH').textContent = 'Sin conexión';
      $('#dMsg').textContent = `Este equipo no envía datos ${ago(a.segundos_sin_datos)}. Los valores de abajo son los últimos que recibimos.`;
      add('Revisa que el equipo esté encendido y conectado a la red.');
      add('Comprueba que el agente (NexMaintAgent) siga abierto en ese equipo.');
    } else {
      $('#dAdvH').textContent = { bajo: 'Todo en orden', medio: 'Programa una revisión', alto: 'Requiere mantenimiento' }[r];
      $('#dMsg').textContent = a.mensaje;
      if (r !== 'bajo') (a.recomendacion || '').split(/(?<=\.)\s+/).filter(Boolean).forEach(add);
    }
    for (const k of ['cpu', 'ram', 'disco']) {
      const g = $(`.g[data-k="${k}"]`, drawer);
      setRing($('.ring', g), a[k], on ? level(k, a[k]) : 'off');
      const b = $('.gv', g); tween(b, a[k]);
    }
    $('#thermo').dataset.est = est ? '1' : '0';
    $('#thermoTitle').textContent = est ? 'Temperatura estimada' : 'Temperatura';
    $('#thermoNote').hidden = !est;
    $('#capTemp').textContent = est ? 'Temperatura estimada en las últimas mediciones' : 'Temperatura en las últimas mediciones';
    const pos = clamp((a.temperatura - 30) / 80 * 100, 0, 100);
    $('#mark').style.left = pos + '%';
    $('#markV').textContent = (est ? '~' : '') + a.temperatura + ' °C';
    const hist = d.historial;
    const cpuV = hist.map(p => p.cpu), tV = hist.map(p => p.temperatura);
    $('#chCpu').innerHTML = chart('cpu', cpuV, { min: 0, max: 100, thr: 90, unit: '%', label: 'CPU', lvl: on ? level('cpu', a.cpu) : 'off' });
    // Si es estimada no se dibuja el umbral de riesgo: esa temperatura no entra en el cálculo
    $('#chTemp').innerHTML = chart('temp', tV, { min: 30, max: 110, thr: est ? null : 80, unit: '°C',
      label: est ? 'Temperatura estimada' : 'Temperatura', lvl: !on || est ? 'off' : level('temp', a.temperatura) });
    $('#dFree').textContent = `Espacio libre en disco: ${a.espacio_libre} GB`;
    $('#dWhen').textContent = `Última medición: ${a.fecha}`;
  }

  async function refreshDrawer() {
    const name = st.sel; if (!name) return;
    try { const d = await j('/api/equipos/' + encodeURIComponent(name)); if (st.sel === name) paintDrawer(name, d); } catch { /* se reintenta en el siguiente ciclo */ }
  }

  function openDrawer(name, trigger) {
    st.sel = name; st.trigger = trigger;
    drawer.inert = false; drawer.classList.add('open'); scrim.classList.add('open');
    $('#dTitle').textContent = name;
    refreshDrawer();
    setTimeout(() => $('#dClose').focus(), 60);
  }
  function closeDrawer() {
    if (!st.sel) return;
    st.sel = null;
    drawer.classList.remove('open'); scrim.classList.remove('open'); drawer.inert = true;
    st.trigger && st.trigger.isConnected && st.trigger.focus();
  }
  $('#dClose').addEventListener('click', closeDrawer);
  scrim.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', e => {
    if (!st.sel) return;
    if (e.key === 'Escape') { closeDrawer(); return; }
    if (e.key === 'Tab') {
      const f = $$('button, [href], summary', drawer).filter(el => !el.disabled);
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });

  /* Estado de conexión y reloj */
  function tick() {
    const now = new Date();
    $('#clock').textContent = now.toLocaleTimeString('es-CO', { hour12: false });
    const live = $('#live'), txt = $('#liveText');
    const idle = Math.round((Date.now() - st.lastChange) / 1000);
    if (!st.ok) { live.dataset.state = 'off'; txt.textContent = st.first ? 'Conectando…' : 'Sin conexión con el servidor. Reintentando…'; }
    else if (st.tiles.size && idle > 10) { live.dataset.state = 'stale'; txt.textContent = `Sin mediciones nuevas hace ${idle} s`; }
    else { live.dataset.state = 'live'; txt.textContent = 'En vivo'; }
  }
  setInterval(tick, 1000); tick();

  /* Modo demostración: "Simular fallo" lleva a PC-DEMO de normal a crítico en ~30 s */
  async function demoEstado(eq) {
    try {
      const d = await j('/api/demo'), btn = $('#demoBtn');
      btn.disabled = d.activo;
      btn.textContent = d.activo ? 'Simulando…' : 'Simular fallo';
      $('#demoReset').hidden = !eq.some(e => e.nombre === NOMBRE_DEMO);
    } catch { /* la demo es opcional: si falla, no afecta al resto */ }
  }
  async function initDemo() {
    try { const c = await j('/api/config'); st.demo = !!c.demo; $('#demoBox').hidden = !st.demo; } catch { /* sin demo */ }
  }
  $('#demoBtn').addEventListener('click', async () => {
    $('#demoBtn').disabled = true;
    try { await j('/api/demo/fallo', { method: 'POST' }); } catch { /* ya estaba en curso */ }
    poll();
  });
  $('#demoReset').addEventListener('click', async () => {
    try { await j('/api/demo/reset', { method: 'POST' }); } catch { /* nada que quitar */ }
    st.alertSig = '';
    poll();
  });

  /* Ciclo de actualización */
  let timer = null, busy = false;
  async function poll() {
    if (busy) return; busy = true; clearTimeout(timer);
    try {
      const [eq, al] = await Promise.all([j('/api/equipos'), j('/api/alertas')]);
      eq.sort((a, b) => a.nombre.localeCompare(b.nombre, undefined, { numeric: true }));
      if (st.first) { await seedHistory(eq); st.lastChange = Date.now(); }
      st.ok = true;
      renderFloor(eq); renderSummary(eq); renderAlerts(al);
      if (st.sel) refreshDrawer();
      if (st.demo) await demoEstado(eq);
      st.first = false;
    } catch { st.ok = false; }
    finally { busy = false; tick(); timer = setTimeout(poll, POLL_MS); }
  }
  initDemo().then(poll);
})();
