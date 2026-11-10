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
  const estado = e => e.conectado ? safeR(e.nivel) : 'offline';
  const etiqueta = r => r === 'offline' ? 'Sin conexión' : 'Riesgo ' + LABEL[r].toLowerCase();
  const ESTADOS = ['bajo', 'medio', 'alto', 'offline'];
  const CIRC = 2 * Math.PI * 42;
  const POLL_MS = 2000, HIST_MAX = 30;

  const st = { tiles: new Map(), hist: new Map(), seenAlerts: null, alertSig: null, sel: null, trigger: null,
               lastChange: Date.now(), ok: false, first: true, conectado: false, demoBusy: false };

  const j = async (url, opts) => { const r = await fetch(url, { cache: 'no-store', ...opts }); if (!r.ok) throw new Error(r.status); return r.json(); };

  function duracion(segundos) {
    if (segundos < 60) return segundos + ' s';
    const partes = [];
    const dias = Math.floor(segundos / 86400), horas = Math.floor(segundos / 3600) % 24, minutos = Math.floor(segundos / 60) % 60;
    if (dias) partes.push(dias + ' d');
    if (horas) partes.push(horas + ' h');
    if (minutos) partes.push(minutos + ' min');
    return partes.join(' ');
  }

  function ultimaMedicion(e) {
    if (e.segundos_sin_datos == null) return 'Sin mediciones';
    const texto = e.conectado ? 'Actualizado' : 'Última lectura';
    return texto + ' hace ' + duracion(e.segundos_sin_datos);
  }

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
            <span class="stat temp" data-level="bajo"><b class="v-temp" data-v="0">0</b><span>°C</span><small class="temp-source" hidden>Estimada</small></span>
          </span>
        </span>
        <svg class="spark" viewBox="0 0 200 34" preserveAspectRatio="none" aria-hidden="true"><path class="sa"/><path class="sl"/></svg>
        <span class="reading"></span>
      </span>
      <span class="stand"></span><span class="base"></span>`;
    $('.name', b).textContent = name;
    b.addEventListener('animationend', () => b.classList.remove('enter'), { once: true });
    b.addEventListener('click', () => openDrawer(name, b));
    return b;
  }

  function updateTile(tile, e) {
    const risk = estado(e), t = e.temperatura;
    tile.dataset.risk = risk;
    tile.style.setProperty('--heat', e.conectado && !e.temp_estimada ? clamp(((t ?? 40) - 40) / 50, 0, 1).toFixed(2) : '0');
    $('.tagtxt', tile).textContent = etiqueta(risk);
    $('.tag use', tile).setAttribute('href', '#i-' + risk);
    const cpu = e.cpu ?? 0;
    setRing($('.ring', tile), cpu, e.conectado ? level('cpu', cpu) : 'offline');
    tween($('.v-cpu', tile), e.cpu);
    for (const k of ['ram', 'disco']) {
      const s = $(`.stat[data-k="${k}"]`, tile), v = e[k] ?? 0, bar = $('i', s);
      bar.style.width = clamp(v, 0, 100) + '%';
      bar.style.background = `var(--${e.conectado ? level(k, v) : 'offline'})`;
      tween($('.nv', s), e[k]);
    }
    tween($('.v-temp', tile), t);
    $('.stat.temp', tile).dataset.level = e.temp_estimada || !e.conectado ? 'bajo' : level('temp', t ?? 0);
    $('.temp-source', tile).hidden = !e.temp_estimada;
    const lectura = ultimaMedicion(e);
    $('.reading', tile).textContent = lectura;
    tile.setAttribute('aria-label', `${e.nombre}, ${etiqueta(risk)}, ${lectura}. Abrir detalle`);
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
    const nombres = new Set(eq.map(e => e.nombre));
    for (const [nombre, tile] of st.tiles) {
      if (nombres.has(nombre)) continue;
      if (st.sel === nombre) closeDrawer();
      tile.remove();
      st.tiles.delete(nombre);
      st.hist.delete(nombre);
    }
    let fresh = false;
    eq.forEach((e, i) => {
      let tile = st.tiles.get(e.nombre);
      if (!tile) { tile = makeTile(e.nombre, i); st.tiles.set(e.nombre, tile); fresh = true; if (!st.first) tile.classList.remove('enter'); }
      if (floor.children[i] !== tile) floor.insertBefore(tile, floor.children[i] || null);
    });
    if (fresh) void floor.offsetWidth;
    eq.forEach(e => { const h = trackHistory(e); const tile = st.tiles.get(e.nombre); updateTile(tile, e); spark(tile, h.cpu); });
    $('#demoReset').disabled = st.demoBusy || !st.tiles.has('PC-DEMO');
  }

  /* Resumen */
  function renderSummary(eq) {
    const c = { bajo: 0, medio: 0, alto: 0, offline: 0 };
    eq.forEach(e => c[estado(e)]++);
    for (const r of ESTADOS) {
      const seg = $('#seg-' + r);
      seg.style.flexGrow = c[r]; seg.classList.toggle('on', c[r] > 0);
      tween($('#n-' + r), c[r]);
    }
    const names = r => eq.filter(e => estado(e) === r).map(e => e.nombre).join(', ');
    let worst = 'bajo', txt = 'Todos los equipos funcionan con normalidad.';
    if (!eq.length) txt = 'Esperando datos de los equipos…';
    else if (c.alto) { worst = 'alto'; txt = (c.alto === 1 ? 'Requiere mantenimiento: ' : 'Requieren mantenimiento: ') + names('alto') + '.'; }
    else if (c.medio) { worst = 'medio'; txt = 'Conviene revisar: ' + names('medio') + '.'; }
    else if (c.offline) { worst = 'offline'; txt = 'Sin conexión: ' + names('offline') + '.'; }
    $('#sumTxt').textContent = txt;
    $('#sumLine').dataset.risk = worst;
    $('#sumIc').setAttribute('href', '#i-' + worst);
    $('#stack').setAttribute('aria-label', `${c.bajo} equipos en riesgo bajo, ${c.medio} en medio, ${c.alto} en alto y ${c.offline} sin conexión`);
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
        try { await j(`/api/alertas/${a.id}/resolver`, { method: 'POST' }); await poll(); } catch { b.disabled = false; }
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
      ${o.thr == null ? '' : `
        <line x1="${pl}" x2="${W - pr}" y1="${y(o.thr)}" y2="${y(o.thr)}" stroke="var(--alto)" stroke-width="1.4" stroke-dasharray="5 5"/>
        <text x="${pl + 6}" y="${last >= o.thr ? y(o.thr) + 16 : y(o.thr) - 6}" style="fill:var(--text)">${o.guia}</text>`}
      <path d="${area}" fill="url(#g-${id})"/>
      <path d="${line}" fill="none" style="stroke:var(--${o.lvl})" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/>
      <circle class="dot-ping" cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="4.5" style="fill:var(--${o.lvl})"/>
      <circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="5" style="fill:var(--${o.lvl})" stroke="#171132" stroke-width="2"/>
    </svg>`;
  }

  function paintDrawer(name, d) {
    const a = d.actual, r = estado(a);
    $('#dTitle').textContent = name;
    $('#dTag').dataset.risk = r;
    $('#dTag use').setAttribute('href', '#i-' + r);
    $('#dTagTxt').textContent = etiqueta(r);
    $('#dAdvice').dataset.risk = r;
    $('#dAdvH').textContent = { bajo: 'Todo en orden', medio: 'Programa una revisión', alto: 'Requiere mantenimiento', offline: 'Sin conexión' }[r];
    $('#dMsg').textContent = a.conectado ? a.mensaje : 'Los valores corresponden a la última lectura recibida.';
    const ul = $('#dRec'); ul.replaceChildren();
    if (r === 'medio' || r === 'alto') (a.recomendacion || '').split(/(?<=\.)\s+/).filter(Boolean).forEach(t => { const li = document.createElement('li'); li.textContent = t; ul.append(li); });
    for (const k of ['cpu', 'ram', 'disco']) {
      const g = $(`.g[data-k="${k}"]`, drawer);
      setRing($('.ring', g), a[k], a.conectado ? level(k, a[k]) : 'offline');
      const b = $('.gv', g); tween(b, a[k]);
    }
    const pos = clamp((a.temperatura - 30) / 80 * 100, 0, 100);
    $('#mark').style.left = pos + '%';
    $('#markV').textContent = a.temperatura + ' °C';
    $('#dThermo').classList.toggle('estimated', a.temp_estimada);
    $('#dTempTitle').textContent = a.temp_estimada ? 'Temperatura estimada' : 'Temperatura';
    const hist = d.historial;
    const cpuV = hist.map(p => p.cpu), tV = hist.map(p => p.temperatura);
    const incluyeEstimadas = hist.some(p => p.temp_estimada);
    const tituloTemp = incluyeEstimadas ? 'Temperatura (incluye estimaciones)' : 'Temperatura';
    $('#dTempChartTitle').textContent = tituloTemp + ' en las últimas mediciones';
    $('#chCpu').innerHTML = chart('cpu', cpuV, { min: 0, max: 100, thr: 90, guia: 'Uso alto de CPU desde 90 %', unit: '%', label: 'CPU', lvl: level('cpu', a.cpu) });
    $('#chTemp').innerHTML = chart('temp', tV, { min: 30, max: 110, thr: incluyeEstimadas ? null : 80, guia: 'Temperatura alta desde 80 °C', unit: '°C', label: tituloTemp, lvl: incluyeEstimadas ? 'offline' : level('temp', a.temperatura) });
    $('#dFree').textContent = `Espacio libre en disco: ${a.espacio_libre} GB`;
    $('#dUptime').textContent = a.uptime_segundos == null ? 'Tiempo encendido sin datos' : `Tiempo encendido al medir: ${duracion(a.uptime_segundos)}`;
    $('#dWhen').textContent = `${ultimaMedicion(a)} (${a.fecha})`;
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
    else if (!st.tiles.size) { live.dataset.state = 'stale'; txt.textContent = 'Esperando mediciones…'; }
    else if (!st.conectado) { live.dataset.state = 'stale'; txt.textContent = 'Ningún equipo conectado'; }
    else if (idle > 10) { live.dataset.state = 'stale'; txt.textContent = `Sin mediciones nuevas hace ${idle} s`; }
    else { live.dataset.state = 'live'; txt.textContent = 'En vivo'; }
  }
  setInterval(tick, 1000); tick();

  /* Demostración */
  async function cambiarDemo(accion) {
    const iniciar = accion === 'fallo';
    const mensaje = $('#demoMessage');
    st.demoBusy = true;
    $('#demoStart').disabled = true;
    $('#demoReset').disabled = true;
    try {
      await j('/api/demo/' + accion, { method: 'POST' });
      mensaje.textContent = iniciar ? 'PC-DEMO subirá a riesgo alto en unos 30 s.' : 'Simulación retirada.';
      await poll();
    } catch (error) {
      mensaje.textContent = error.message === '409'
        ? (iniciar ? 'La simulación ya está en curso.' : 'Espera unos segundos y vuelve a quitar la simulación.')
        : 'No se pudo completar la acción de la simulación.';
    } finally {
      st.demoBusy = false;
      $('#demoStart').disabled = false;
      $('#demoReset').disabled = !st.tiles.has('PC-DEMO');
    }
  }
  $('#demoStart').addEventListener('click', () => cambiarDemo('fallo'));
  $('#demoReset').addEventListener('click', () => cambiarDemo('reset'));
  j('/api/config').then(config => { $('#demoControls').hidden = !config.demo; }).catch(() => {});

  /* Ciclo de actualización */
  let timer = null, busy = false;
  async function poll() {
    if (busy) return; busy = true; clearTimeout(timer);
    try {
      const [eq, al] = await Promise.all([j('/api/equipos'), j('/api/alertas')]);
      eq.sort((a, b) => a.nombre.localeCompare(b.nombre, undefined, { numeric: true }));
      if (st.first) { await seedHistory(eq); st.lastChange = Date.now(); }
      st.ok = true;
      st.conectado = eq.some(e => e.conectado);
      renderFloor(eq); renderSummary(eq); renderAlerts(al);
      if (st.sel) refreshDrawer();
      st.first = false;
    } catch { st.ok = false; }
    finally { busy = false; tick(); timer = setTimeout(poll, POLL_MS); }
  }
  poll();
})();
