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

async function refreshStats() {
  const data = await fetchJSON("/api/stats");
  const s = data.summary;
  const returnEl = document.getElementById("statReturn");
  returnEl.textContent = `${s.total_return_pct >= 0 ? "+" : ""}${s.total_return_pct.toFixed(2)}%`;
  returnEl.style.color = s.total_return_pct >= 0 ? "#4ade80" : "#f87171";
  document.getElementById("statWinRate").textContent = `${(s.win_rate * 100).toFixed(1)}%`;
  document.getElementById("statDrawdown").textContent = `${s.max_drawdown_pct.toFixed(2)}%`;
  document.getElementById("statTradeCount").textContent = s.trade_count;

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

async function refreshTrades() {
  const trades = await fetchJSON("/api/trades");
  const tbody = document.querySelector("#tradesTable tbody");
  tbody.innerHTML = "";
  for (const t of trades) {
    const tr = document.createElement("tr");
    const time = new Date(t.ts * 1000).toLocaleString();
    tr.innerHTML = `
      <td>${time}</td>
      <td>${t.symbol}</td>
      <td class="${t.action}">${t.action.toUpperCase()}</td>
      <td>${t.price.toFixed(4)}</td>
      <td>${t.qty.toFixed(6)}</td>
      <td>${t.reason ?? ""}</td>`;
    tbody.appendChild(tr);
  }
}

async function refreshSignals() {
  const signals = await fetchJSON("/api/signals");
  const grid = document.getElementById("signalGrid");
  grid.innerHTML = "";
  for (const s of signals) {
    const div = document.createElement("div");
    div.className = "signal-card" + (s.symbol === selectedSymbol ? " selected" : "");
    div.innerHTML = `
      <div class="symbol">${s.symbol}</div>
      <div class="badge ${s.action}">${actionLabel(s.action)}</div>
      <div class="price">${s.price.toFixed(4)}</div>
      <div class="reason">${s.reason ?? ""}</div>
      <div class="ago">${timeAgo(s.ts)}</div>`;
    div.addEventListener("click", () => selectSymbol(s.symbol));
    grid.appendChild(div);
  }
  populateBacktestSymbols(signals.map(s => s.symbol));
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
  if (same) return;
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
    status.textContent = "Önce bir coin seç (üstteki sinyal panelinde henüz coin görünmüyorsa bot henüz sinyal üretmemiştir).";
    status.classList.add("error");
    return;
  }

  const body = {
    symbol,
    limit: parseInt(document.getElementById("btLimit").value, 10) || 1000,
    walk_forward: parseInt(document.getElementById("btSplits").value, 10) || 4,
  };
  const period = document.getElementById("btPeriod").value;
  const oversold = document.getElementById("btOversold").value;
  const overbought = document.getElementById("btOverbought").value;
  if (period || oversold || overbought) {
    body.params = {};
    if (period) body.params.period = parseInt(period, 10);
    if (oversold) body.params.oversold = parseInt(oversold, 10);
    if (overbought) body.params.overbought = parseInt(overbought, 10);
  }

  button.disabled = true;
  status.classList.remove("error");
  status.textContent = `${symbol} için geçmiş veri çekiliyor ve test ediliyor... (birkaç saniye sürebilir)`;
  results.innerHTML = "";

  try {
    const res = await fetch("/api/backtest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      status.textContent = data.error || `Hata (HTTP ${res.status})`;
      status.classList.add("error");
      return;
    }

    status.textContent = `${data.symbol} — ${data.candles} mum (${data.timeframe}), strateji: ${data.strategy}, ${data.periods.length} dönem.`;

    let html = "";
    if (data.avg_return_pct !== undefined) {
      html += `<div class="bt-summary">
        <div class="stat"><div class="label">Ortalama Getiri</div><div class="value">${fmtPct(data.avg_return_pct)}</div></div>
        <div class="stat"><div class="label">En Kötü Dönem</div><div class="value">${fmtPct(data.worst_period_pct)}</div></div>
        <div class="stat"><div class="label">En İyi Dönem</div><div class="value">${fmtPct(data.best_period_pct)}</div></div>
      </div>`;
    }
    html += `<table class="bt-periods"><thead><tr>
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
    html += "</tbody></table>";
    results.innerHTML = html;
  } catch (err) {
    status.textContent = `İstek başarısız: ${err}`;
    status.classList.add("error");
  } finally {
    button.disabled = false;
  }
}

document.getElementById("btRun").addEventListener("click", runBacktest);

async function selectSymbol(symbol) {
  selectedSymbol = symbol;
  document.querySelectorAll(".signal-card").forEach(el => {
    el.classList.toggle("selected", el.querySelector(".symbol").textContent === symbol);
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

async function refreshAll() {
  await Promise.all([refreshEquity(), refreshTrades(), refreshStats(), refreshSignals()]);
  if (selectedSymbol) await selectSymbol(selectedSymbol);
}

refreshAll();
setInterval(refreshAll, 10000);
