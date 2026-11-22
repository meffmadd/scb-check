/* Plotly-specific presentation stays here; the payload contains only raw report data. */
(() => {
  "use strict";
  const payload = JSON.parse(document.getElementById("report-data").textContent);

  function escapeText(value) {
    return String(value).replace(/[&<>"']/g, character => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&#34;", "'": "&#39;"
    })[character]);
  }

  function displayUnit(unit) {
    return unit === "fraction" ? "percent" : unit;
  }

  function measurement(value, unit) {
    if (value === null) return "unavailable";
    return unit === "fraction" ? `${value * 100}%` : `${value} ${unit}`;
  }

  function hoverText(series, name, input) {
    const tau = series.tau === null ? "N/A" : series.tau.toFixed(2);
    const lines = [name, payload.labels[input],
      `Value: ${measurement(series.values[input], series.unit)}`, `τ: ${tau}`];
    return lines.filter(line => line !== "").map(escapeText).join("<br>");
  }

  for (const [index, series] of payload.runs[0].series.entries()) {
    const scale = series.unit === "fraction" ? 100 : 1;
    const element = document.getElementById(`plot-${index}`);
    const traces = payload.runs.map(run => {
      const item = run.series[index];
      return {
        type: "scatter", mode: "lines+markers", name: escapeText(run.name || "Snapshots"),
        x: item.values.map((_, input) => input + 1),
        y: item.values.map(value => value === null ? null : value * scale), connectgaps: false,
        text: item.values.map((_, input) => hoverText(item, run.name, input)),
        hovertemplate: "%{text}<extra></extra>", marker: {size: 7}
      };
    });
    function labels() {
      // Wrap even unbroken directory names; keep full labels at narrow widths.
      const width = Math.max(8, Math.min(24, Math.floor(element.clientWidth / payload.labels.length / 8)));
      const wrapped = payload.labels.map(label => Array.from(label).reduce((chunks, char, offset) => {
        if (offset % width === 0) chunks.push("");
        chunks[chunks.length - 1] += char;
        return chunks;
      }, []));
      element.style.height = `${320 + Math.max(...wrapped.map(chunks => chunks.length)) * 16}px`;
      return wrapped.map(chunks => chunks.map(escapeText).join("<br>"));
    }
    function fail(error) {
      const message = document.createElement("p");
      message.textContent = `Plot unavailable: ${String(error)}.`;
      element.replaceChildren(message);
    }
    try {
      Plotly.newPlot(element, traces, {
        autosize: true, hovermode: "closest", showlegend: false,
        margin: {l: 80, r: 30, t: 30, b: 70},
        xaxis: {
          tickmode: "array", tickvals: payload.labels.map((_, input) => input + 1),
          ticktext: labels(), tickangle: 0, automargin: true, title: {text: "Input order"}
        },
        yaxis: {
          title: {text: displayUnit(series.unit)},
          automargin: true, rangemode: "tozero", zeroline: true
        }
      }, {responsive: true, displayModeBar: false}).catch(fail);
      function resize() {
        // Closed native disclosures have no chart layout; redraw when reopened instead.
        if (!element.clientWidth) return;
        Plotly.relayout(element, {
          "xaxis.ticktext": labels(), width: element.clientWidth, height: element.clientHeight
        }).catch(fail);
      }
      window.addEventListener("resize", resize);
      element.closest(".metric-group").addEventListener("toggle", resize);
    } catch (error) {
      fail(error);
    }
  }
})();
