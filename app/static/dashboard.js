const CHART_COLOR = "#4da3ff";
const CHART_COLOR_2 = "#3ecf8e";

const chartInstances = {};

function destroyIfExists(canvasId) {
  if (chartInstances[canvasId]) {
    chartInstances[canvasId].destroy();
    delete chartInstances[canvasId];
  }
}

function lineChart(ctx, labels, data, label, color) {
  destroyIfExists(ctx.id);
  const chart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        label,
        data,
        borderColor: color,
        backgroundColor: color + "33",
        tension: 0.3,
        fill: true,
        pointRadius: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { ticks: { color: "#8b96a5", maxTicksLimit: 6 }, grid: { color: "#262e3a" } },
        y: { ticks: { color: "#8b96a5" }, grid: { color: "#262e3a" } },
      },
      plugins: { legend: { display: false } },
    },
  });
  chartInstances[ctx.id] = chart;
  return chart;
}

function barChart(ctx, labels, datasets) {
  destroyIfExists(ctx.id);
  const chart = new Chart(ctx, {
    type: "bar",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { ticks: { color: "#8b96a5" }, grid: { color: "#262e3a" } },
        y: { ticks: { color: "#8b96a5" }, grid: { color: "#262e3a" }, beginAtZero: true },
      },
      plugins: { legend: { labels: { color: "#8b96a5" } } },
    },
  });
  chartInstances[ctx.id] = chart;
  return chart;
}

function fmtTime(ts) {
  return ts ? ts.replace("T", " ").slice(0, 19) : "";
}

async function loadHistory(metric) {
  const res = await fetch(`/api/switches/${switchId}/history?metric=${metric}`);
  const rows = await res.json();
  return {
    labels: rows.map(r => fmtTime(r.collected_at).slice(5)),
    values: rows.map(r => r.metric_value),
  };
}

async function renderStatCards(summary) {
  const grid = document.getElementById("stat-grid");
  const re = summary.routing_engine || {};
  const up = summary.uptime || {};
  const ver = summary.version || {};
  const cards = [
    ["Model", ver.model || "-"],
    ["Junos Version", ver.junos_version || "-"],
    ["Uptime", up.uptime_text || "-"],
    ["CPU", re.cpu_util_pct != null ? re.cpu_util_pct + "%" : "-"],
    ["Memory", re.memory_util_pct != null ? re.memory_util_pct + "%" : "-"],
    ["Interfaces Up", summary.interfaces ? summary.interfaces.interfaces_up : "-"],
  ];
  grid.innerHTML = cards.map(([label, value]) =>
    `<div class="stat-card"><div class="label">${label}</div><div class="value">${value}</div></div>`
  ).join("");
}

async function renderCharts() {
  const [cpu, mem, temp, storage, up, down, sysAlarm, chAlarm] = await Promise.all([
    loadHistory("cpu_util_pct"),
    loadHistory("memory_util_pct"),
    loadHistory("re_temperature_c"),
    loadHistory("root_storage_used_pct"),
    loadHistory("interfaces_up"),
    loadHistory("interfaces_down"),
    loadHistory("system_alarm_count"),
    loadHistory("chassis_alarm_count"),
  ]);

  lineChart(document.getElementById("chart-cpu"), cpu.labels, cpu.values, "CPU %", CHART_COLOR);
  lineChart(document.getElementById("chart-mem"), mem.labels, mem.values, "Mem %", CHART_COLOR);
  lineChart(document.getElementById("chart-temp"), temp.labels, temp.values, "Temp C", "#f0a830");
  lineChart(document.getElementById("chart-storage"), storage.labels, storage.values, "Storage %", "#ef5a5a");

  barChart(document.getElementById("chart-iface"), up.labels, [
    { label: "Up", data: up.values, backgroundColor: CHART_COLOR_2 },
    { label: "Down", data: down.values, backgroundColor: "#ef5a5a" },
  ]);

  barChart(document.getElementById("chart-alarms"), sysAlarm.labels, [
    { label: "System Alarms", data: sysAlarm.values, backgroundColor: "#f0a830" },
    { label: "Chassis Alarms", data: chAlarm.values, backgroundColor: "#ef5a5a" },
  ]);
}

async function renderSummary() {
  const res = await fetch(`/api/switches/${switchId}/summary`);
  const data = await res.json();
  const banner = document.getElementById("status-banner");

  if (data.status === "no_data") {
    banner.style.display = "block";
    banner.className = "status-banner info";
    banner.textContent = "No data collected yet. Click 'Collect Now' to run the first collection.";
    return;
  }
  if (data.status === "error") {
    banner.style.display = "block";
    banner.className = "status-banner error";
    banner.textContent = `Last collection failed: ${data.error_message}`;
  } else {
    banner.style.display = "none";
  }

  renderStatCards(data.summary || {});

  document.getElementById("version-box").textContent = (data.raw && data.raw.version) || "n/a";
  document.getElementById("log-box").textContent = (data.raw && data.raw.log_messages) || "n/a";
}

async function renderHistoryTable() {
  const res = await fetch(`/api/switches/${switchId}/collections`);
  const rows = await res.json();
  const tbody = document.querySelector("#history-table tbody");
  tbody.innerHTML = rows.map(r =>
    `<tr><td>${fmtTime(r.collected_at)}</td><td>${r.status}</td><td>${r.error_message || ""}</td></tr>`
  ).join("");
}

document.getElementById("collect-now").addEventListener("click", async () => {
  const btn = document.getElementById("collect-now");
  btn.disabled = true;
  btn.textContent = "Collecting...";
  await fetch(`/api/switches/${switchId}/collect`, { method: "POST" });
  setTimeout(async () => {
    await init();
    btn.disabled = false;
    btn.textContent = "Collect Now";
  }, 8000);
});

async function init() {
  await renderSummary();
  await renderCharts();
  await renderHistoryTable();
}

init();
