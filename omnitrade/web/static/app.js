async function fetchJSON(url) {
  const res = await fetch(url);
  return res.json();
}

let equityChart, drawdownChart, signalChart;
let selectedSymbol = null;
let signalChartSymbol = null; // hangi coin şu an signalChart'ta çizili — gereksiz destroy/recreate'i önlemek için

function timeAgo(ts) {
  const diffSec = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (diffSec < 60) return `${diffSec}s önce`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}dk önce`;
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return `${diffHour}sa önce`;
  return `${Math.floor(diffHour / 24)}gün önce`;
}

// action -> long/short görünümü: BUY = long (pozisyon aç), SELL = short/çık
// anlamında gösteriliyor (bot spot/uzun-only çalışıyor, "short" burada
// pozisyondan çıkış/aşırı-alım sinyali anlamında kullanılıyor).
function actionLabel(action) {
  if (action === "buy") return "LONG (AL)";
  if (action === "sell") return "SHORT (SAT)";
  return "HOLD";
}

// --- Faz 12: görsel/UX cilası — küçük paylaşılan yardımcılar ---
// Toast bildirimleri, canlı durum rozeti, iskelet (skeleton) temizleme ve
// boş durum mesajları burada toplanıyor; her biri mevcut fonksiyonlardan
// (refreshStats/refreshSignals/refreshTrades/vb.) çağrılıyor, hiçbiri
// mevcut element id'lerini veya event akışını değiştirmiyor.

function showToast(message, type = "info") {
  const stack = document.getElementById("toastStack");
  if (!stack || !message) return;
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  stack.appendChild(toast);
  const remove = () => {
    toast.classList.add("leaving");
    setTimeout(() => toast.remove(), 200);
  };
  setTimeout(remove, 4000);
  toast.addEventListener("click", remove);
}

function setStatus(elId, message, type) {
  // type: "error" | "success" | undefined (nötr)
  const el = document.getElementById(elId);
  if (!el) return;
  el.textContent = message;
  el.classList.toggle("error", type === "error");
  el.classList.toggle("success", type === "success");
}

let lastRefreshOk = null;
function setLiveStatus(ok) {
  const dot = document.getElementById("liveDot");
  const text = document.getElementById("liveStatusText");
  if (!dot || !text) return;
  if (ok) {
    dot.classList.remove("stale");
    text.textContent = `canlı · son güncelleme ${new Date().toLocaleTimeString()}`;
  } else {
    dot.classList.add("stale");
    text.textContent = "bağlantı sorunu — tekrar deneniyor…";
  }
  if (lastRefreshOk === false && ok) showToast("Bağlantı yeniden kuruldu.", "success");
  lastRefreshOk = ok;
}

function clearSkeleton(...ids) {
  for (const id of ids) document.getElementById(id)?.classList.remove("skeleton");
}

async function refreshStats() {
  const data = await fetchJSON("/api/stats");
  const s = data.summary;
  const returnEl = document.getElementById("statReturn");
  returnEl.textContent = `${s.total_return_pct >= 0 ? "+" : ""}${s.total_return_pct.toFixed(2)}%`;
  returnEl.style.color = s.total_return_pct >= 0 ? "#4ade80" : "#f87171";
  document.getElementById("statWinRate").textContent = `${(s.win_rate * 100).toFixed(1)}%`;
  document.getElementById("statDrawdown").textContent = `${s.max_drawdown_pct.toFixed(2)}%`;
  document.getElementById("statTradeCount").textContent = s.trade_count;
  clearSkeleton("statReturn", "statWinRate", "statDrawdown", "statTradeCount");

  const labels = data.drawdown_curve.map(d => new Date(d.ts * 1000).toLocaleString());
  const values = data.drawdown_curve.map(d => -d.drawdown_pct);

  if (!drawdownChart) {
    const ctx = document.getElementById("drawdownChart").getContext("2d");
    drawdownChart = new Chart(ctx, {
      type: "line",
      data: { labels, datasets: [{ label: "Drawdown %", data: values, borderColor: "#f87171", backgroundColor: "rgba(248,113,113,0.15)", fill: true, tension: 0.2, pointRadius: 0 }] },
      options: { plugins: { legend: { display: false } }, scales: { x: { display: false } } },
    });
  } else {
    drawdownChart.data.labels = labels;
    drawdownChart.data.datasets[0].data = values;
    drawdownChart.update();
  }
}

async function refreshEquity() {
  const data = await fetchJSON("/api/equity");
  const labels = data.map(d => new Date(d.ts * 1000).toLocaleString());
  const values = data.map(d => d.balance);

  if (!equityChart) {
    const ctx = document.getElementById("equityChart").getContext("2d");
    equityChart = new Chart(ctx, {
      type: "line",
      data: { labels, datasets: [{ label: "Equity", data: values, borderColor: "#60a5fa", tension: 0.2, pointRadius: 0 }] },
      options: { plugins: { legend: { display: false } }, scales: { x: { display: false } } },
    });
  } else {
    equityChart.data.labels = labels;
    equityChart.data.datasets[0].data = values;
    equityChart.update();
  }
}

// Faz 12: en son bilinen ilk işlemin zaman damgası — yeni bir işlem
// geldiğinde (poll döngüsünde tepedeki satır değiştiğinde) o satırı kısa
// süreliğine vurgulamak (flash) için kullanılıyor.
let lastTopTradeTs = null;

function emptyStateRow(colspan, icon, message) {
  const tr = document.createElement("tr");
  tr.className = "empty-row";
  tr.innerHTML = `<td colspan="${colspan}">${icon} ${message}</td>`;
  return tr;
}

async function refreshTrades() {
  const trades = await fetchJSON("/api/trades");
  const tbody = document.querySelector("#tradesTable tbody");
  tbody.innerHTML = "";

  if (!trades.length) {
    tbody.appendChild(emptyStateRow(6, "🕓", "Henüz kapanmış işlem yok — bot sinyal ürettikçe burada listelenecek."));
    lastTopTradeTs = null;
    return;
  }

  trades.forEach((t, i) => {
    const tr = document.createElement("tr");
    const time = new Date(t.ts * 1000).toLocaleString();
    tr.innerHTML = `
      <td>${time}</td>
      <td>${t.symbol}</td>
      <td class="${t.action}">${t.action.toUpperCase()}</td>
      <td>${t.price.toFixed(4)}</td>
      <td>${t.qty.toFixed(6)}</td>
      <td>${t.reason ?? ""}</td>`;
    if (i === 0 && lastTopTradeTs !== null && t.ts !== lastTopTradeTs) {
      tr.classList.add("flash-new");
      setTimeout(() => tr.classList.remove("flash-new"), 2500);
    }
    tbody.appendChild(tr);
  });
  lastTopTradeTs = trades[0].ts;
}

async function refreshSignals() {
  const signals = await fetchJSON("/api/signals");
  const grid = document.getElementById("signalGrid");
  grid.innerHTML = "";

  if (!signals.length) {
    const div = document.createElement("div");
    div.className = "empty-state";
    div.innerHTML = `<span class="big">📡</span>Henüz sinyal üretilmedi.<br>Bot ilk döngüsünü tamamladığında coinler burada görünecek.`;
    grid.appendChild(div);
    populateBacktestSymbols([]);
    return;
  }

  for (const s of signals) {
    const div = document.createElement("div");
    div.className = "signal-card" + (s.symbol === selectedSymbol ? " selected" : "");
    div.tabIndex = 0;
    div.innerHTML = `
      <div class="symbol">${s.symbol}</div>
      <div class="badge ${s.action}">${actionLabel(s.action)}</div>
      <div class="price">${s.price.toFixed(4)}</div>
      <div class="reason">${s.reason ?? ""}</div>
      <div class="ago">${timeAgo(s.ts)}</div>`;
    div.addEventListener("click", () => selectSymbol(s.symbol));
    div.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectSymbol(s.symbol); }
    });
    grid.appendChild(div);
  }
  populateBacktestSymbols(signals.map(s => s.symbol));
}

// --- Faz 10: dashboard'dan coin ekle/çıkar ---
// --- Faz 11: tek tıkla dry-run config uygulama için de burada tutulan
// dry_run/pair_strategies durumu kullanılıyor (bkz. updateApplyRowVisibility) ---

let dashboardDryRun = true;
let dashboardPairStrategies = {};

async function refreshPairChips() {
  const data = await fetchJSON("/api/config/pairs");
  dashboardDryRun = data.dry_run;
  dashboardPairStrategies = data.pair_strategies || {};
  const container = document.getElementById("pairChips");
  container.innerHTML = "";
  for (const symbol of data.pairs) {
    const chip = document.createElement("span");
    chip.className = "pair-chip";
    chip.innerHTML = `${symbol} <button type="button" title="Kaldır">×</button>`;
    chip.querySelector("button").addEventListener("click", () => removePair(symbol, chip));
    container.appendChild(chip);
  }
  updateApplyRowVisibility();
}

function setPairStatus(message, isError) {
  setStatus("pairStatus", message, isError ? "error" : "success");
}

async function postPairAction(symbol, action) {
  const res = await fetch("/api/config/pairs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol, action }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `Hata (HTTP ${res.status})`);
  return data;
}

async function addPair() {
  const input = document.getElementById("pairInput");
  const button = document.getElementById("pairAdd");
  const symbol = input.value.trim();
  if (!symbol) return;
  button.disabled = true;
  try {
    const data = await postPairAction(symbol, "add");
    input.value = "";
    setPairStatus(data.message, false);
    showToast(`${symbol} eklendi. ${data.message}`, "success");
    await refreshPairChips();
  } catch (err) {
    setPairStatus(err.message, true);
    showToast(err.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function removePair(symbol, chipEl) {
  chipEl.querySelector("button").disabled = true;
  try {
    const data = await postPairAction(symbol, "remove");
    setPairStatus(data.message, false);
    showToast(`${symbol} kaldırıldı. ${data.message}`, "success");
    await refreshPairChips();
  } catch (err) {
    setPairStatus(err.message, true);
    showToast(err.message, "error");
    chipEl.querySelector("button").disabled = false;
  }
}

document.getElementById("pairAdd").addEventListener("click", addPair);
document.getElementById("pairInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") addPair();
});

// --- Faz 8: strateji dropdown + parametre formu backend'den otomatik ---

let strategySchemas = [];

async function loadStrategies() {
  strategySchemas = await fetchJSON("/api/strategies");
  const select = document.getElementById("btStrategy");
  const lbSelect = document.getElementById("lbStrategies");
  for (const s of strategySchemas) {
    const opt = document.createElement("option");
    opt.value = s.name;
    opt.textContent = s.name;
    select.appendChild(opt);

    const lbOpt = document.createElement("option");
    lbOpt.value = s.name;
    lbOpt.textContent = s.name;
    lbOpt.selected = true; // varsayılan: hepsini karşılaştır
    lbSelect.appendChild(lbOpt);
  }
  renderStrategyParams();
}

function renderStrategyParams() {
  const strategyName = document.getElementById("btStrategy").value;
  const container = document.getElementById("btParams");
  container.innerHTML = "";
  const schema = strategySchemas.find(s => s.name === strategyName);
  if (!schema) return; // "— canlı ayar —" seçiliyse hiç parametre alanı gösterme
  for (const p of schema.params) {
    const label = document.createElement("label");
    label.textContent = p.name;
    const input = document.createElement("input");
    input.type = "number";
    input.step = "any";
    input.dataset.param = p.name;
    input.placeholder = p.default === null ? "" : `örn. ${p.default}`;
    label.appendChild(input);
    container.appendChild(label);
  }
}

document.getElementById("btStrategy").addEventListener("change", renderStrategyParams);

function collectStrategyParams() {
  const params = {};
  document.querySelectorAll("#btParams input[data-param]").forEach(input => {
    if (input.value !== "") params[input.dataset.param] = parseFloat(input.value);
  });
  return params;
}

// --- Faz 6: dashboard'dan backtest/walk-forward ---

function populateBacktestSymbols(symbols) {
  const select = document.getElementById("btSymbol");
  const current = select.value;
  const existing = new Set(Array.from(select.options).map(o => o.value));
  const incoming = new Set(symbols);
  // Sadece fark varsa yeniden kur — her poll'da select'i sıfırlamak
  // kullanıcının açık dropdown'ını/seçimini bozar.
  const same = existing.size === incoming.size && [...existing].every(v => incoming.has(v));
  if (!same) {
    select.innerHTML = "";
    for (const sym of symbols) {
      const opt = document.createElement("option");
      opt.value = sym;
      opt.textContent = sym;
      select.appendChild(opt);
    }
    if (symbols.includes(current)) select.value = current;
    else if (selectedSymbol && symbols.includes(selectedSymbol)) select.value = selectedSymbol;
  }

  const lbSelect = document.getElementById("lbSymbols");
  const lbExisting = new Set(Array.from(lbSelect.options).map(o => o.value));
  if (lbExisting.size !== incoming.size || ![...lbExisting].every(v => incoming.has(v))) {
    lbSelect.innerHTML = "";
    for (const sym of symbols) {
      const opt = document.createElement("option");
      opt.value = sym;
      opt.textContent = sym;
      opt.selected = true; // varsayılan: hepsini karşılaştır
      lbSelect.appendChild(opt);
    }
  }
}

function fmtPct(v) {
  const cls = v >= 0 ? "bt-pos" : "bt-neg";
  return `<span class="${cls}">${v >= 0 ? "+" : ""}${v.toFixed(2)}%</span>`;
}

async function runBacktest() {
  const symbol = document.getElementById("btSymbol").value;
  const status = document.getElementById("btStatus");
  const results = document.getElementById("btResults");
  const button = document.getElementById("btRun");
  if (!symbol) {
    setStatus("btStatus", "Önce bir coin seç (üstteki sinyal panelinde henüz coin görünmüyorsa bot henüz sinyal üretmemiştir).", "error");
    return;
  }

  const body = {
    symbol,
    limit: parseInt(document.getElementById("btLimit").value, 10) || 1000,
    walk_forward: parseInt(document.getElementById("btSplits").value, 10) || 4,
  };
  const strategyName = document.getElementById("btStrategy").value;
  const explicitParams = collectStrategyParams();
  if (strategyName) {
    body.strategy = strategyName;
    if (Object.keys(explicitParams).length) body.params = explicitParams;
  }

  button.disabled = true;
  setStatus("btStatus", `${symbol} için geçmiş veri çekiliyor ve test ediliyor... (birkaç saniye sürebilir)`);
  results.innerHTML = "";
  lastBacktestApply = null;
  document.getElementById("btApplyStatus").textContent = "";
  updateApplyRowVisibility();

  try {
    const res = await fetch("/api/backtest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      setStatus("btStatus", data.error || `Hata (HTTP ${res.status})`, "error");
      return;
    }

    setStatus("btStatus", `${data.symbol} — ${data.candles} mum (${data.timeframe}), strateji: ${data.strategy}, ${data.periods.length} dönem.`, "success");

    let html = "";
    if (data.avg_return_pct !== undefined) {
      html += `<div class="bt-summary">
        <div class="stat"><div class="label">Ortalama Getiri</div><div class="value">${fmtPct(data.avg_return_pct)}</div></div>
        <div class="stat"><div class="label">En Kötü Dönem</div><div class="value">${fmtPct(data.worst_period_pct)}</div></div>
        <div class="stat"><div class="label">En İyi Dönem</div><div class="value">${fmtPct(data.best_period_pct)}</div></div>
      </div>`;
    }
    html += `<div class="table-scroll"><table class="bt-periods"><thead><tr>
      <th>Dönem</th><th>İşlem</th><th>Getiri</th><th>Kazanma Oranı</th><th>Max Drawdown</th>
    </tr></thead><tbody>`;
    for (const p of data.periods) {
      html += `<tr>
        <td>${p.label}</td>
        <td>${p.trades}</td>
        <td>${fmtPct(p.total_return_pct)}</td>
        <td>${(p.win_rate * 100).toFixed(1)}%</td>
        <td>${p.max_drawdown_pct.toFixed(2)}%</td>
      </tr>`;
    }
    html += "</tbody></table></div>";
    results.innerHTML = html;
    results.classList.remove("fade-in");
    void results.offsetWidth; // reflow — animasyonu yeniden tetiklemek için
    results.classList.add("fade-in");

    // Faz 11: sadece açıkça bir strateji seçildiyse (dropdown "— canlı
    // ayar —" değilse) "uygula" anlamlı — canlı ayarı kendine uygulamak
    // no-op olurdu. Buton görünürlüğü ayrıca dry_run olmasına da bağlı,
    // bkz. updateApplyRowVisibility().
    if (strategyName) {
      lastBacktestApply = { symbol: data.symbol, strategy: strategyName, params: explicitParams };
    } else {
      lastBacktestApply = null;
    }
    updateApplyRowVisibility();
  } catch (err) {
    setStatus("btStatus", `İstek başarısız: ${err}`, "error");
  } finally {
    button.disabled = false;
  }
}

document.getElementById("btRun").addEventListener("click", runBacktest);

// --- Faz 11: backtest sonucunu tek tıkla dry-run pair_strategies'e uygula ---

let lastBacktestApply = null; // { symbol, strategy, params } — en son çalıştırılan backtest

function updateApplyRowVisibility() {
  const row = document.getElementById("btApplyRow");
  const resetBtn = document.getElementById("btReset");
  if (!lastBacktestApply || !dashboardDryRun) {
    row.style.display = "none";
    return;
  }
  row.style.display = "flex";
  const hasOverride = Object.prototype.hasOwnProperty.call(dashboardPairStrategies, lastBacktestApply.symbol);
  resetBtn.style.display = hasOverride ? "inline-block" : "none";
}

async function postPairStrategyAction(payload) {
  const res = await fetch("/api/config/pair-strategy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `Hata (HTTP ${res.status})`);
  return data;
}

async function applyBacktestStrategy() {
  if (!lastBacktestApply) return;
  const button = document.getElementById("btApply");
  button.disabled = true;
  try {
    const data = await postPairStrategyAction({
      symbol: lastBacktestApply.symbol, action: "apply",
      strategy: lastBacktestApply.strategy, params: lastBacktestApply.params,
    });
    setStatus("btApplyStatus", data.message, "success");
    showToast(data.message, "success");
    dashboardPairStrategies = data.pair_strategies;
    updateApplyRowVisibility();
  } catch (err) {
    setStatus("btApplyStatus", err.message, "error");
    showToast(err.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function resetBacktestStrategy() {
  if (!lastBacktestApply) return;
  const button = document.getElementById("btReset");
  button.disabled = true;
  try {
    const data = await postPairStrategyAction({ symbol: lastBacktestApply.symbol, action: "reset" });
    setStatus("btApplyStatus", data.message, "success");
    showToast(data.message, "success");
    dashboardPairStrategies = data.pair_strategies;
    updateApplyRowVisibility();
  } catch (err) {
    setStatus("btApplyStatus", err.message, "error");
    showToast(err.message, "error");
  } finally {
    button.disabled = false;
  }
}

document.getElementById("btApply").addEventListener("click", applyBacktestStrategy);
document.getElementById("btReset").addEventListener("click", resetBacktestStrategy);

// --- Faz 9: leaderboard — çoklu strateji × coin karşılaştırma ---

async function runLeaderboard() {
  const symbols = Array.from(document.getElementById("lbSymbols").selectedOptions).map(o => o.value);
  const strategies = Array.from(document.getElementById("lbStrategies").selectedOptions).map(o => o.value);
  const results = document.getElementById("lbResults");
  const button = document.getElementById("lbRun");

  if (!symbols.length || !strategies.length) {
    setStatus("lbStatus", "En az bir coin ve bir strateji seç.", "error");
    return;
  }

  const body = {
    symbols,
    strategies,
    limit: parseInt(document.getElementById("lbLimit").value, 10) || 1000,
    walk_forward: parseInt(document.getElementById("lbSplits").value, 10) || 4,
  };

  button.disabled = true;
  setStatus("lbStatus", `${symbols.length} coin × ${strategies.length} strateji test ediliyor... (biraz sürebilir)`);
  results.innerHTML = "";

  try {
    const res = await fetch("/api/backtest/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      setStatus("lbStatus", data.error || `Hata (HTTP ${res.status})`, "error");
      return;
    }

    setStatus("lbStatus", `${data.results.length} kombinasyon test edildi, en iyi getiriye göre sıralı.`, "success");
    let html = `<div class="table-scroll"><table class="bt-periods"><thead><tr>
      <th>#</th><th>Coin</th><th>Strateji</th><th>Ort. Getiri</th><th>En Kötü</th><th>En İyi</th><th>Kazanma Oranı</th><th>Max Drawdown</th><th>İşlem</th>
    </tr></thead><tbody>`;
    data.results.forEach((r, i) => {
      if (r.error) {
        html += `<tr><td>${i + 1}</td><td>${r.symbol}</td><td>${r.strategy}</td>
          <td colspan="6" class="bt-neg">${r.error}</td></tr>`;
        return;
      }
      html += `<tr>
        <td>${i + 1}</td>
        <td>${r.symbol}</td>
        <td>${r.strategy}</td>
        <td>${fmtPct(r.avg_return_pct)}</td>
        <td>${fmtPct(r.worst_period_pct)}</td>
        <td>${fmtPct(r.best_period_pct)}</td>
        <td>${(r.avg_win_rate * 100).toFixed(1)}%</td>
        <td>${r.avg_max_drawdown_pct.toFixed(2)}%</td>
        <td>${r.trades}</td>
      </tr>`;
    });
    html += "</tbody></table></div>";
    results.innerHTML = html;
    results.classList.remove("fade-in");
    void results.offsetWidth;
    results.classList.add("fade-in");
  } catch (err) {
    setStatus("lbStatus", `İstek başarısız: ${err}`, "error");
  } finally {
    button.disabled = false;
  }
}

document.getElementById("lbRun").addEventListener("click", runLeaderboard);

async function selectSymbol(symbol) {
  selectedSymbol = symbol;
  document.querySelectorAll(".signal-card").forEach(el => {
    el.classList.toggle("selected", el.querySelector(".symbol")?.textContent === symbol);
  });

  const detail = document.getElementById("signalDetail");
  detail.classList.add("visible");
  document.getElementById("signalDetailTitle").textContent = `${symbol} — fiyat & sinyaller`;

  const history = await fetchJSON(`/api/signals/history?symbol=${encodeURIComponent(symbol)}&limit=300`);
  const labels = history.map(h => new Date(h.ts * 1000).toLocaleString());
  const prices = history.map(h => h.price);
  const buyPoints = history.map(h => (h.action === "buy" ? h.price : null));
  const sellPoints = history.map(h => (h.action === "sell" ? h.price : null));

  // Aynı coin için tekrar çağrıldıysa (10sn'lik poll döngüsü, kullanıcı
  // coin değiştirmedi) grafiği yok edip yeniden yaratmak yerine verisini
  // yerinde güncelle — önceki davranış her poll'da destroy+recreate
  // yapıyordu, bu da görünür bir titreme/flicker'a yol açıyordu.
  if (signalChart && signalChartSymbol === symbol) {
    signalChart.data.labels = labels;
    signalChart.data.datasets[0].data = prices;
    signalChart.data.datasets[1].data = buyPoints;
    signalChart.data.datasets[2].data = sellPoints;
    signalChart.update();
    return;
  }

  const ctx = document.getElementById("signalChart").getContext("2d");
  const datasets = [
    { label: "Fiyat", data: prices, borderColor: "#60a5fa", tension: 0.2, pointRadius: 0 },
    { label: "LONG (AL)", data: buyPoints, borderColor: "#4ade80", backgroundColor: "#4ade80", showLine: false, pointRadius: 6, pointStyle: "triangle" },
    { label: "SHORT (SAT)", data: sellPoints, borderColor: "#f87171", backgroundColor: "#f87171", showLine: false, pointRadius: 6, pointStyle: "rectRot" },
  ];

  if (signalChart) signalChart.destroy();
  signalChart = new Chart(ctx, {
    type: "line",
    data: { labels, datasets },
    options: { scales: { x: { display: false } } },
  });
  signalChartSymbol = symbol;
}

// --- Faz 12: nav scrollspy — üstteki bölüm bağlantılarını, kullanıcının
// hangi kart hizasında olduğuna göre otomatik vurgular ---
function setupSectionNav() {
  const links = Array.from(document.querySelectorAll("#sectionNav a"));
  const idToLink = new Map(links.map(a => [a.getAttribute("href").slice(1), a]));
  const sections = links.map(a => document.getElementById(a.getAttribute("href").slice(1))).filter(Boolean);
  if (!sections.length || !("IntersectionObserver" in window)) return;

  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        links.forEach(a => a.classList.remove("active"));
        idToLink.get(entry.target.id)?.classList.add("active");
      }
    }
  }, { rootMargin: "-15% 0px -70% 0px", threshold: 0 });

  sections.forEach(s => observer.observe(s));
}

async function refreshAll() {
  try {
    await Promise.all([refreshEquity(), refreshTrades(), refreshStats(), refreshSignals()]);
    if (selectedSymbol) await selectSymbol(selectedSymbol);
    setLiveStatus(true);
  } catch (err) {
    setLiveStatus(false);
  }
}

refreshAll();
loadStrategies();
refreshPairChips();
setupSectionNav();
setInterval(refreshAll, 10000);
