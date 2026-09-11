async function fetchJSON(url) {
  const res = await fetch(url);
  return res.json();
}

let chart;

async function refreshEquity() {
  const data = await fetchJSON("/api/equity");
  const labels = data.map(d => new Date(d.ts * 1000).toLocaleString());
  const values = data.map(d => d.balance);

  if (!chart) {
    const ctx = document.getElementById("equityChart").getContext("2d");
    chart = new Chart(ctx, {
      type: "line",
      data: { labels, datasets: [{ label: "Equity", data: values, borderColor: "#60a5fa", tension: 0.2 }] },
      options: { plugins: { legend: { display: false } }, scales: { x: { display: false } } },
    });
  } else {
    chart.data.labels = labels;
    chart.data.datasets[0].data = values;
    chart.update();
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

async function refreshAll() {
  await Promise.all([refreshEquity(), refreshTrades()]);
}

refreshAll();
setInterval(refreshAll, 10000);
