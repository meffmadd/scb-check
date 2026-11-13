# Plotly.js basic distribution

## Provenance

- Version: **3.0.1**, official `plotly.js-basic-dist-min` npm package.
- Asset: [`plotly-basic.min.js`](plotly-basic.min.js), unchanged, including upstream banner.
- Official distribution: <https://cdn.plot.ly/plotly-basic-3.0.1.min.js>
- Package metadata: <https://registry.npmjs.org/plotly.js-basic-dist-min/3.0.1>
- Package archive: <https://registry.npmjs.org/plotly.js-basic-dist-min/-/plotly.js-basic-dist-min-3.0.1.tgz>
- Release: <https://github.com/plotly/plotly.js/releases/tag/v3.0.1>
- MIT license: [`LICENSE.plotly.txt`](LICENSE.plotly.txt), copied verbatim from
  <https://raw.githubusercontent.com/plotly/plotly.js/v3.0.1/LICENSE>.

The npm archive was verified against its registry SHA-512 integrity value;
its JavaScript was byte-identical to the official CDN asset. The npm license
was byte-identical to the tagged upstream license. No local build or patches.

| File | SHA-256 |
| --- | --- |
| `plotly-basic.min.js` | `9750237b42d97af386c25ad644d858ac5b7735dd65e8583e32c9234d551db7f4` |
| `LICENSE.plotly.txt` | `8c45d9eaf50c2f72dd9c7ab9ef440788ba58a3538484b5c51c1f17d5128752e7` |
| npm archive | `50f8f54fbb687f9fa1c31082ab4fb24594ed2a644c9e893a87b5f966db972b68` |

Registry archive integrity:
`sha512-2DNfjn0Xv+IAk6ksaIm8AHSlKCxWQOx9f3v5JGvzFKPwEbJRsLIy4Up0cOPqO53kL4jrdw8LnUTrM9FAzvKMsQ==`.

This basic build supports SVG scatter lines/markers, hover labels, and responsive
sizing. Reports use SVG scatter only, not WebGL. The renderer embeds the bundle
once and includes its license; no network is needed to generate or open reports.

## Updating

1. Select an official tagged release and its matching npm basic distribution.
2. Verify the archive's registry integrity; compare extracted JavaScript with
   the versioned official CDN asset and its license with the tagged release.
3. Replace the JavaScript and upstream license without editing either; update
   the version, URLs, integrity, and SHA-256 values above.
4. Build wheel and sdist, verify all vendor assets are present, and test rendering
   from an installed wheel outside the checkout.
5. Run the standalone browser acceptance runner using the pinned tool environment
   documented in `tests/reporting/report_browser_smoke.py`.

Network access is required only for vendoring and browser-tool installation.
