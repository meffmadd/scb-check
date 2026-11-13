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

  function hoverText(series, input, difference) {
    const value = (difference ? series.differences : series.values)[input];
    return [
      payload.labels[input],
      `${difference ? "Change" : "Value"}: ${measurement(value, series.unit, difference)}`
    ].map(escapeText).join("<br>");
  }

  for (const [index, series] of payload.series.entries()) {
    for (const difference of [false, true]) {
      const raw = difference ? series.differences : series.values;
      const scale = series.unit === "fraction" ? 100 : 1;
      const element = document.getElementById(`plot-${index}-${Number(difference)}`);
      const y = raw.map(value => value === null ? null : value * scale);
      function labels() {
        // Wrap even unbroken directory names; keep full labels at narrow widths.
        const width = Math.max(8, Math.min(24, Math.floor(element.clientWidth / payload.paths.length / 8)));
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
        Plotly.newPlot(element, [{
          type: "scatter", mode: "lines+markers",
          x: raw.map((_, input) => input + 1), y, connectgaps: false,
          text: raw.map((_, input) => hoverText(series, input, difference)),
          hovertemplate: "%{text}<extra></extra>", marker: {size: 7}
        }], {
          autosize: true, hovermode: "closest", showlegend: false,
          margin: {l: 80, r: 30, t: 30, b: 70},
          xaxis: {
            tickmode: "array", tickvals: y.map((_, input) => input + 1),
            ticktext: labels(), tickangle: 0, automargin: true, title: {text: "Input order"}
          },
          yaxis: {
            title: {text: displayUnit(series.unit, difference)},
            automargin: true, rangemode: "tozero", zeroline: true
          }
        }, {responsive: true, displayModeBar: false}).catch(fail);
        window.addEventListener("resize", () => {
          Plotly.relayout(element, {
            "xaxis.ticktext": labels(), width: element.clientWidth, height: element.clientHeight
          }).catch(fail);
        });
      } catch (error) {
        fail(error);
      }
    }
  }
})();
