async function fetchJSON(url) {
  const res = await fetch(url);
  if (res.status === 401) {
    // Faz 14: web_auth açık ama tarayıcı henüz kimlik bilgisi göndermedi
    // (ya da yanlış). Sessizce yutmuyoruz — kullanıcıya tek seferlik bir
    // ipucu gösteriyoruz; tarayıcının kendi Basic Auth popup'ı zaten
    // devreye girer, biz sadece anlamsız bir JSON parse hatasını
    // engelliyoruz.
    setLiveStatus(false, true);
    throw new Error("401 Unauthorized");
  }
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
function setLiveStatus(ok, unauthorized = false) {
  const dot = document.getElementById("liveDot");
  const text = document.getElementById("liveStatusText");
  if (!dot || !text) return;
  if (ok) {
    dot.classList.remove("stale");
    text.textContent = `canlı · son güncelleme ${new Date().toLocaleTimeString()}`;
  } else if (unauthorized) {
    dot.classList.add("stale");
    text.textContent = "kimlik doğrulama gerekli";
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
    // FIX: sinyal ile gerçekleşen işlem farkı görünmüyordu (ör. pozisyon
    // yokken üretilen bir "sell" hiçbir işlem yapmaz ama kart aynı görünürdü)
    // ve hangi stratejinin sinyal verdiği hiç yazmıyordu. İkisi de artık
    // backend'den geliyor (bkz. storage.py strategy kolonu / executed alanı).
    const strategyLabel = s.strategy ? `<div class="strategy">${s.strategy}</div>` : "";
    const executedLabel = (s.action !== "hold")
      ? (s.executed
          ? `<div class="exec-tag exec-yes">işlem yapıldı</div>`
          : `<div class="exec-tag exec-no">sadece sinyal (işlem yok)</div>`)
      : "";
    div.innerHTML = `
      <div class="symbol">${s.symbol}</div>
      ${strategyLabel}
      <div class="badge ${s.action}">${actionLabel(s.action)}</div>
      <div class="price">${s.price.toFixed(4)}</div>
      <div class="reason">${s.reason ?? ""}</div>
      ${executedLabel}
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

// --- Faz 18: Karşılaştırma (Leaderboard) şablonları — isimlendirilmiş
// coin/strateji/mum sayısı/walk-forward seçimini kaydedip tek tıkla
// tekrar uygulama. Sunucu tarafı sadece kaydet/listele/sil yapıyor
// (bkz. storage.py) — "Karşılaştır"ı gerçekten çalıştırmak hâlâ mevcut
// runLeaderboard()'un işi, şablon sadece formu ÖN DOLDURUYOR.
let leaderboardTemplates = {};

async function loadLeaderboardTemplates() {
  const templates = await fetchJSON("/api/leaderboard/templates");
  leaderboardTemplates = Object.fromEntries(templates.map(t => [t.name, t]));
  const select = document.getElementById("lbTemplateSelect");
  const current = select.value;
  select.innerHTML = '<option value="">— seç —</option>';
  for (const t of templates) {
    const opt = document.createElement("option");
    opt.value = t.name;
    opt.textContent = t.name;
    select.appendChild(opt);
  }
  if (templates.some(t => t.name === current)) select.value = current;
}

function applyLeaderboardTemplate() {
  const name = document.getElementById("lbTemplateSelect").value;
  const t = leaderboardTemplates[name];
  if (!t) {
    setStatus("lbTemplateStatus", "Önce bir şablon seç.", "error");
    return;
  }
  for (const opt of document.getElementById("lbSymbols").options) {
    opt.selected = t.symbols.includes(opt.value);
  }
  for (const opt of document.getElementById("lbStrategies").options) {
    opt.selected = t.strategies.includes(opt.value);
  }
  document.getElementById("lbLimit").value = t.candle_limit;
  document.getElementById("lbSplits").value = t.walk_forward;
  setStatus("lbTemplateStatus", `"${name}" şablonu forma uygulandı.`, "success");
}

async function saveLeaderboardTemplate() {
  const nameInput = document.getElementById("lbTemplateName");
  const name = nameInput.value.trim();
  const symbols = Array.from(document.getElementById("lbSymbols").selectedOptions).map(o => o.value);
  const strategies = Array.from(document.getElementById("lbStrategies").selectedOptions).map(o => o.value);
  if (!name) {
    setStatus("lbTemplateStatus", "Şablon için bir isim yaz.", "error");
    return;
  }
  if (!symbols.length || !strategies.length) {
    setStatus("lbTemplateStatus", "Kaydetmeden önce en az bir coin ve bir strateji seç.", "error");
    return;
  }
  try {
    const res = await fetch("/api/leaderboard/templates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: "save", name, symbols, strategies,
        candle_limit: parseInt(document.getElementById("lbLimit").value, 10) || 1000,
        walk_forward: parseInt(document.getElementById("lbSplits").value, 10) || 4,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `Hata (HTTP ${res.status})`);
    nameInput.value = "";
    await loadLeaderboardTemplates();
    document.getElementById("lbTemplateSelect").value = name;
    setStatus("lbTemplateStatus", `"${name}" kaydedildi.`, "success");
  } catch (err) {
    setStatus("lbTemplateStatus", err.message, "error");
  }
}

async function deleteLeaderboardTemplate() {
  const select = document.getElementById("lbTemplateSelect");
  const name = select.value;
  if (!name) {
    setStatus("lbTemplateStatus", "Önce silinecek bir şablon seç.", "error");
    return;
  }
  if (!confirm(`"${name}" şablonunu silmek istediğine emin misin?`)) return;
  try {
    const res = await fetch("/api/leaderboard/templates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "delete", name }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `Hata (HTTP ${res.status})`);
    await loadLeaderboardTemplates();
    setStatus("lbTemplateStatus", `"${name}" silindi.`, "success");
  } catch (err) {
    setStatus("lbTemplateStatus", err.message, "error");
  }
}

document.getElementById("lbTemplateApply").addEventListener("click", applyLeaderboardTemplate);
document.getElementById("lbTemplateSave").addEventListener("click", saveLeaderboardTemplate);
document.getElementById("lbTemplateDelete").addEventListener("click", deleteLeaderboardTemplate);

async function selectSymbol(symbol) {
  selectedSymbol = symbol;
  document.querySelectorAll(".signal-card").forEach(el => {
    el.classList.toggle("selected", el.querySelector(".symbol")?.textContent === symbol);
  });

  const detail = document.getElementById("signalDetail");
  detail.classList.add("visible");

  const history = await fetchJSON(`/api/signals/history?symbol=${encodeURIComponent(symbol)}&limit=300`);
  // FIX: grafik başlığı hangi stratejinin bu sinyalleri ürettiğini hiç
  // söylemiyordu (kullanıcı "strateji değiştirsem ne olurdu göremiyorum"
  // diyordu) — en azından şu an AKTİF olanı burada gösteriyoruz. Coin
  // başına aynı anda tek strateji çalıştığı için (bkz. config pair_strategies)
  // geçmiş sinyallerin çoğu zaten bu stratejiye ait olacaktır; strateji
  // değiştirilmiş geçmiş noktalar ayrı renkte işaretlenir (aşağıda).
  const activeStrategy = history.length ? history[history.length - 1].strategy : "";
  document.getElementById("signalDetailTitle").textContent =
    `${symbol} — fiyat & sinyaller${activeStrategy ? ` (${activeStrategy})` : ""}`;
  const prices = history.map(h => h.price);
  // Gerçekten pozisyon açan/kapatan (executed=1) sinyaller dolu üçgen/kare;
  // stratejinin ürettiği ama hiçbir işleme yol açmadığı (ör. pozisyon
  // yokken gelen sell) ham sinyaller SOLUK noktalarla ayrı gösterilir —
  // önceden ikisi aynı görünüyordu, bu da "hep sat sinyali var ama işlem
  // yok" karışıklığına yol açıyordu.
  const buyPoints = history.map(h => (h.action === "buy" && h.executed ? h.price : null));
  const sellPoints = history.map(h => (h.action === "sell" && h.executed ? h.price : null));
  const buyOnlyPoints = history.map(h => (h.action === "buy" && !h.executed ? h.price : null));
  const sellOnlyPoints = history.map(h => (h.action === "sell" && !h.executed ? h.price : null));
  const labels = history.map(h => new Date(h.ts * 1000).toLocaleString());

  // Aynı coin için tekrar çağrıldıysa (10sn'lik poll döngüsü, kullanıcı
  // coin değiştirmedi) grafiği yok edip yeniden yaratmak yerine verisini
  // yerinde güncelle — önceki davranış her poll'da destroy+recreate
  // yapıyordu, bu da görünür bir titreme/flicker'a yol açıyordu.
  if (signalChart && signalChartSymbol === symbol) {
    signalChart.data.labels = labels;
    signalChart.data.datasets[0].data = prices;
    signalChart.data.datasets[1].data = buyPoints;
    signalChart.data.datasets[2].data = sellPoints;
    signalChart.data.datasets[3].data = buyOnlyPoints;
    signalChart.data.datasets[4].data = sellOnlyPoints;
    signalChart.update();
    return;
  }

  const ctx = document.getElementById("signalChart").getContext("2d");
  const datasets = [
    { label: "Fiyat", data: prices, borderColor: "#60a5fa", tension: 0.2, pointRadius: 0 },
    { label: "LONG (işlem açıldı)", data: buyPoints, borderColor: "#4ade80", backgroundColor: "#4ade80", showLine: false, pointRadius: 7, pointStyle: "triangle" },
    { label: "SHORT (işlem kapandı)", data: sellPoints, borderColor: "#f87171", backgroundColor: "#f87171", showLine: false, pointRadius: 7, pointStyle: "rectRot" },
    { label: "AL sinyali (işlem yok)", data: buyOnlyPoints, borderColor: "#4ade80", backgroundColor: "rgba(74,222,128,0.25)", showLine: false, pointRadius: 4, pointStyle: "triangle" },
    { label: "SAT sinyali (işlem yok)", data: sellOnlyPoints, borderColor: "#f87171", backgroundColor: "rgba(248,113,113,0.25)", showLine: false, pointRadius: 4, pointStyle: "rectRot" },
  ];

  if (signalChart) signalChart.destroy();
  signalChart = new Chart(ctx, {
    type: "line",
    data: { labels, datasets },
    options: { scales: { x: { display: false } } },
  });
  signalChartSymbol = symbol;
}

// --- Faz 16: canlı/dry-run modu + poll aralığı — bkz. AUDIT_REPORT.md §6.1
// için üç ön koşul: (1) web_auth kapalıyken canlıya geçiş uç noktası 403
// döner, dashboard bunu "Canlıya Geç" butonunu devre dışı bırakarak +
// uyarı göstererek yansıtır; (2) canlıya geçiş tek istekle olmaz, sabit
// bir onay metni gerektirir (modal burada); (3) her değişiklik salt-okunur
// audit log'a yazılır (aşağıdaki tablo bunu gösterir).

const LIVE_CHECKLIST_SUMMARY = [
  "Strateji doğrulaması: birden fazla piyasa rejiminde backtest + en az birkaç hafta kesintisiz dry-run + pozitif getiri",
  "Risk parametreleri (stop-loss/take-profit/max_daily_loss) gerçek risk toleransına göre gözden geçirildi",
  "Borsa API anahtarı SADECE trade izinli — withdrawal kapalı, IP whitelist yapıldı",
  "Telegram bildirimleri + healthcheck cron + günlük DB yedeği kurulu",
  "Küçük bir gerçek bakiye ile başlanacak, ilk işlemler yakından izlenecek",
];

function renderChecklistSummary() {
  const list = document.getElementById("sysChecklist");
  if (!list || list.childElementCount) return;
  for (const item of LIVE_CHECKLIST_SUMMARY) {
    const li = document.createElement("li");
    li.textContent = item;
    list.appendChild(li);
  }
}

function modePillHtml(dryRun) {
  return dryRun
    ? '<span class="mode-pill dry">🟢 DRY-RUN</span>'
    : '<span class="mode-pill live">🔴 CANLI</span>';
}

async function refreshAuditLog() {
  const rows = await fetchJSON("/api/system/audit-log?limit=20");
  const tbody = document.querySelector("#auditTable tbody");
  tbody.innerHTML = "";
  if (!rows.length) {
    tbody.appendChild(emptyStateRow(6, "📜", "Henüz mod değişikliği yok."));
    return;
  }
  for (const row of rows) {
    const tr = document.createElement("tr");
    const dt = new Date(row.ts * 1000).toLocaleString();
    const dir = row.action === "go_live" ? "→ CANLI" : "→ DRY-RUN";
    tr.innerHTML = `
      <td>${dt}</td>
      <td>${row.username || "—"}</td>
      <td>${row.ip || "—"}</td>
      <td>${dir}</td>
      <td>${row.old_dry_run} → ${row.new_dry_run}</td>
      <td>${row.old_live_trading_confirmed} → ${row.new_live_trading_confirmed}</td>`;
    tbody.appendChild(tr);
  }
}

async function refreshSystem() {
  const data = await fetchJSON("/api/system");
  document.getElementById("sysFileMode").innerHTML = modePillHtml(data.config_file.dry_run);
  document.getElementById("sysRuntimeMode").innerHTML = modePillHtml(data.runtime.dry_run);
  document.getElementById("sysPollValue").textContent = `${data.runtime.poll_interval_seconds}sn`;
  document.getElementById("sysPollInput").value = data.runtime.poll_interval_seconds;
  document.getElementById("sysRestartBanner").style.display = data.restart_required ? "block" : "none";
  document.getElementById("sysAuthWarning").style.display = data.web_auth_enabled ? "none" : "block";
  document.getElementById("sysGoLive").disabled = !data.web_auth_enabled;
  await refreshAuditLog();
}

async function applyPollInterval() {
  const input = document.getElementById("sysPollInput");
  const button = document.getElementById("sysPollApply");
  const seconds = parseInt(input.value, 10);
  if (!Number.isFinite(seconds)) return;
  button.disabled = true;
  try {
    const res = await fetch("/api/system/poll-interval", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ seconds }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `Hata (HTTP ${res.status})`);
    setStatus("sysPollStatus", data.message, "success");
    showToast(data.message, "success");
    await refreshSystem();
  } catch (err) {
    setStatus("sysPollStatus", err.message, "error");
    showToast(err.message, "error");
  } finally {
    button.disabled = false;
  }
}

document.getElementById("sysPollApply").addEventListener("click", applyPollInterval);

// Canlıya geçiş modalını, ihtiyaç duyulan sabit onay metnini SUNUCUDAN
// alarak açıyoruz (confirm_text'i BOŞ göndererek — bu 400 döner ama config'e
// dokunmaz, audit log'a yazmaz; bkz. server.py). Böylece metin hem tek bir
// yerde tanımlı kalır hem de yanlışlıkla ekrana eski/hatalı bir metin
// yazılmaz.
async function openLiveConfirmModal() {
  try {
    const res = await fetch("/api/system/live-mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "go_live" }),
    });
    const data = await res.json();
    if (res.status === 403) {
      showToast(data.error, "error");
      return;
    }
    const phrase = data.required_confirm_text || "CANLIYA GEÇİYORUM, RİSKİ ANLADIM";
    document.getElementById("confirmPhraseDisplay").textContent = phrase;
    document.getElementById("confirmPhraseInput").value = "";
    setStatus("confirmPhraseStatus", "", undefined);
    document.getElementById("confirmModalOverlay").style.display = "flex";
    document.getElementById("confirmPhraseInput").focus();
  } catch (err) {
    showToast(err.message, "error");
  }
}

function closeLiveConfirmModal() {
  document.getElementById("confirmModalOverlay").style.display = "none";
}

async function submitLiveConfirm() {
  const phrase = document.getElementById("confirmPhraseInput").value;
  const button = document.getElementById("confirmPhraseSubmit");
  button.disabled = true;
  try {
    const res = await fetch("/api/system/live-mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "go_live", confirm_text: phrase }),
    });
    const data = await res.json();
    if (!res.ok) {
      setStatus("confirmPhraseStatus", data.error, "error");
      return;
    }
    closeLiveConfirmModal();
    setStatus("sysModeStatus", data.message, "success");
    showToast("Canlı moda geçildi — config.yaml güncellendi, restart gerekiyor.", "success");
    await refreshSystem();
  } catch (err) {
    setStatus("confirmPhraseStatus", err.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function goDryRun() {
  if (!confirm("Dry-run moduna dönülsün mü? config.yaml güncellenecek, bot restart sonrası uygulayacak.")) return;
  const button = document.getElementById("sysGoDryRun");
  button.disabled = true;
  try {
    const res = await fetch("/api/system/live-mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "go_dry_run" }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `Hata (HTTP ${res.status})`);
    setStatus("sysModeStatus", data.message, "success");
    showToast("Dry-run moduna dönüldü.", "success");
    await refreshSystem();
  } catch (err) {
    setStatus("sysModeStatus", err.message, "error");
    showToast(err.message, "error");
  } finally {
    button.disabled = false;
  }
}

document.getElementById("sysGoLive").addEventListener("click", openLiveConfirmModal);
document.getElementById("sysGoDryRun").addEventListener("click", goDryRun);
document.getElementById("confirmPhraseSubmit").addEventListener("click", submitLiveConfirm);
document.getElementById("confirmPhraseCancel").addEventListener("click", closeLiveConfirmModal);
document.getElementById("confirmPhraseInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") submitLiveConfirm();
  if (e.key === "Escape") closeLiveConfirmModal();
});

// --- Faz 15: sekmeli "kokpit" düzeni — artık tek uzun sayfa scroll'lamak
// yerine, üstteki sekmelerle panel değiştiriliyor. Sayfanın kendisi hiç
// kaymıyor (bkz. index.html `#app { overflow: hidden }`), sadece aktif
// panelin içi (`.panel.active { overflow-y: auto }`) gerekirse kayıyor. ---
function setupTabs() {
  const buttons = Array.from(document.querySelectorAll(".tab-btn"));
  const panels = Array.from(document.querySelectorAll(".panel"));
  if (!buttons.length) return;

  function activate(panelId) {
    buttons.forEach(b => b.classList.toggle("active", b.dataset.panel === panelId));
    panels.forEach(p => p.classList.toggle("active", p.id === panelId));
    // Chart.js canvas'ları gizliyken (display:none) doğru boyutlanmıyor
    // olabilir — panel görünür olduğunda ilgili grafikleri yeniden boyutlandır.
    if (panelId === "panel-performance") {
      equityChart?.resize();
      drawdownChart?.resize();
    }
    if (panelId === "panel-overview" && signalChart) {
      signalChart.resize();
    }
  }

  buttons.forEach(b => b.addEventListener("click", () => activate(b.dataset.panel)));
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

// --- Faz 17: sabit 10sn'lik poll yerine push modeli ---
// (bkz. PLAN.md §7.2, AUDIT_REPORT.md §7 madde 2, server.py _handle_stream)
// Web süreci kendi SQLite'ını kısa aralıklarla yoklayıp SADECE bir şey
// gerçekten değiştiğinde tek bir SSE olayı gönderiyor; tarayıcı da o olayda
// belirtilen veri setini (mevcut refresh* fonksiyonlarıyla, ÇİZİM MANTIĞI
// DEĞİŞMEDEN) normal REST endpoint'inden çekiyor. Bot<->web arasında hâlâ
// doğrudan bir kanal yok (bkz. AUDIT_REPORT.md §1) — bu SADECE web
// sürecinin zaten yaptığı SQLite okumasını tarayıcıya daha hızlı/az
// gereksiz istekle yansıtıyor.
let eventSource = null;

function handleStreamChange(changed) {
  const jobs = [];
  if (changed.includes("trades") || changed.includes("equity")) jobs.push(refreshStats());
  if (changed.includes("trades")) jobs.push(refreshTrades());
  if (changed.includes("equity")) jobs.push(refreshEquity());
  if (changed.includes("signals")) {
    jobs.push(refreshSignals());
    if (selectedSymbol) jobs.push(selectSymbol(selectedSymbol));
  }
  if (changed.includes("system")) jobs.push(refreshSystem());
  return Promise.all(jobs);
}

function connectStream() {
  if (eventSource) eventSource.close();
  eventSource = new EventSource("/api/stream");

  eventSource.onopen = () => setLiveStatus(true);

  eventSource.onmessage = (evt) => {
    setLiveStatus(true);
    let msg;
    try {
      msg = JSON.parse(evt.data);
    } catch (err) {
      return; // beklenmeyen/bozuk gövde — atla, aşağıdaki güvenlik ağı zaten var
    }
    if (msg.type === "update" && Array.isArray(msg.changed) && msg.changed.length) {
      handleStreamChange(msg.changed).catch(() => setLiveStatus(false));
    }
  };

  eventSource.onerror = () => {
    // Tarayıcının EventSource'u KENDİLİĞİNDEN yeniden bağlanmayı dener
    // (readyState CONNECTING'e döner) — burada elle reconnect KURMUYORUZ,
    // sadece rozeti güncelliyoruz.
    setLiveStatus(false);
  };
}

refreshAll();
loadStrategies();
refreshPairChips();
renderChecklistSummary();
refreshSystem();
loadLeaderboardTemplates();
setupTabs();
connectStream();
// Bu ikisi artık ANA güncelleme kanalı DEĞİL, sadece bir güvenlik ağı —
// bazı tarayıcılar arka plandaki sekmelerde EventSource'u kısıtlayabilir
// ya da bağlantı sessizce takılı kalabilir; veri en geç bu aralıkla
// tazelenir. Normal koşulda SSE zaten çok daha hızlı tetikler.
setInterval(refreshAll, 60000);
setInterval(refreshSystem, 60000);
