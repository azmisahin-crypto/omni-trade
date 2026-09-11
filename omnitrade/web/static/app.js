async function fetchJSON(url) {
  const res = await fetch(url);
  return res.json();
}

let equityChart, drawdownChart, signalChart;
let selectedSymbol = null;

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
}

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
}

async function refreshAll() {
  await Promise.all([refreshEquity(), refreshTrades(), refreshStats(), refreshSignals()]);
  if (selectedSymbol) await selectSymbol(selectedSymbol);
}

refreshAll();
setInterval(refreshAll, 10000);
