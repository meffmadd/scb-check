/* Plotly-specific presentation stays here; the payload contains only raw report data. */
(() => {
  "use strict";
  const payload = JSON.parse(document.getElementById("report-data").textContent);

  function escapeText(value) {
    return String(value).replace(/[&<>"']/g, character => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&#34;", "'": "&#39;"
    })[character]);
  }

  function displayUnit(unit, difference) {
    return unit === "fraction" ? (difference ? "percentage points" : "percent") : unit;
  }

  function measurement(value, unit, difference = false) {
    if (value === null) return "unavailable";
    const number = (difference && value >= 0 ? "+" : "") + String(unit === "fraction" ? value * 100 : value);
    return number + (unit === "fraction" && !difference ? "%" : " " + displayUnit(unit, difference));
  }

  function hoverText(series, name, input, difference) {
    const value = (difference ? series.differences : series.values)[input];
    const tau = series.tau === null ? "N/A" : series.tau.toFixed(2);
    const lines = [name, payload.labels[input],
      `${difference ? "Change" : "Value"}: ${measurement(value, series.unit, difference)}`, `τ: ${tau}`];
    return lines.filter(line => line !== "").map(escapeText).join("<br>");
  }

  for (const [index, series] of payload.runs[0].series.entries()) {
    for (const difference of [false, true]) {
      const scale = series.unit === "fraction" ? 100 : 1;
      const element = document.getElementById(`plot-${index}-${Number(difference)}`);
      const traces = payload.runs.map(run => {
        const item = run.series[index];
        const raw = difference ? item.differences : item.values;
        const name = escapeText(run.name || "Snapshots");
        return {
          type: "scatter", mode: "lines+markers", name,
          x: raw.map((_, input) => input + 1),
          y: raw.map(value => value === null ? null : value * scale), connectgaps: false,
          text: raw.map((_, input) => hoverText(item, run.name, input, difference)),
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
            title: {text: displayUnit(series.unit, difference)},
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
  }
})();
