"""
The page itself — the HTML, CSS and JavaScript `voxlib.dashboard` fills in.

Split out of `dashboard.py` because that file held two things at once: the model
(what every number means, and which module owns it) and the page (how it is
drawn). Both are large, and read together the arithmetic was buried under two
thousand lines of stylesheet. Nothing here computes anything — the rule the
model side states is enforced by this file having no imports to compute with.

`TEMPLATE` carries one placeholder, `__MODEL_JSON__`; `dashboard.render` fills
it. The page stays a single self-contained file: data inlined, charts drawn by
hand in SVG, no network at load.
"""

# The palette is the data-viz reference instance, validated for both modes with
# `scripts/validate_palette.js` (2 categorical slots, all six checks PASS light
# and dark). The heat ramp is one hue stepped by distance from the surface — so
# it inverts in dark mode rather than being flipped automatically, because blue
# 700 on a near-black surface is invisible exactly where the value is highest.
TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Spoken English Progress</title>
<style>
  :root {
    color-scheme: light;
    --page: #f9f9f7;
    --surface: #fcfcfb;
    --ink: #0b0b0b;
    --ink-2: #52514e;
    --muted: #898781;
    --grid: #e1e0d9;
    --axis: #c3c2b7;
    --border: rgba(11,11,11,0.10);
    --series-1: #2a78d6;
    --series-2: #eb6834;
    --good: #0ca30c;
    --warning: #fab219;
    --critical: #d03b3b;
    --heat-0: rgba(42,120,214,0.07);
    --heat-1: #9ec5f4;
    --heat-2: #6da7ec;
    --heat-3: #2a78d6;
    --heat-4: #1c5cab;
    --heat-5: #0d366b;
    --quality: #c3c2b7;
    --hollow: #c3c2b7;
    /* Loop state. Never used alone: every dot is paired with the word for it,
       because colour is not a reading. */
    --state-ok: #0ca30c;
    --state-warn: #fab219;
    --state-stale: #d03b3b;
    --state-never: #898781;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) {
      color-scheme: dark;
      --page: #0d0d0d;
      --surface: #1a1a19;
      --ink: #ffffff;
      --ink-2: #c3c2b7;
      --muted: #898781;
      --grid: #2c2c2a;
      --axis: #383835;
      --border: rgba(255,255,255,0.10);
      --series-1: #3987e5;
      --series-2: #d95926;
      --heat-0: rgba(57,135,229,0.10);
      --heat-1: #184f95;
      --heat-2: #256abf;
      --heat-3: #3987e5;
      --heat-4: #86b6ef;
      --heat-5: #cde2fb;
      --quality: #383835;
      --hollow: #4a4a47;
      --state-ok: #35c435;
      --state-warn: #ffc93d;
      --state-stale: #f05a5a;
      --state-never: #898781;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --page: #0d0d0d;
    --surface: #1a1a19;
    --ink: #ffffff;
    --ink-2: #c3c2b7;
    --muted: #898781;
    --grid: #2c2c2a;
    --axis: #383835;
    --border: rgba(255,255,255,0.10);
    --series-1: #3987e5;
    --series-2: #d95926;
    --heat-0: rgba(57,135,229,0.10);
    --heat-1: #184f95;
    --heat-2: #256abf;
    --heat-3: #3987e5;
    --heat-4: #86b6ef;
    --heat-5: #cde2fb;
    --quality: #383835;
    --hollow: #4a4a47;
    --state-ok: #35c435;
    --state-warn: #ffc93d;
    --state-stale: #f05a5a;
    --state-never: #898781;
  }

  * { box-sizing: border-box; }
  body {
    margin: 0;
    padding: 0 16px 64px;
    background: var(--page);
    color: var(--ink);
    font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  .wrap { max-width: 1100px; margin: 0 auto; }

  header { display: flex; flex-wrap: wrap; gap: 12px; align-items: baseline;
           justify-content: space-between; padding: 32px 0 8px; }
  h1 { font-size: 20px; font-weight: 600; margin: 0; letter-spacing: -0.01em; }
  .sub { color: var(--muted); font-size: 13px; }
  button.ghost { background: none; border: 1px solid var(--border); color: var(--ink-2);
                 border-radius: 8px; padding: 5px 10px; font: inherit; font-size: 13px;
                 cursor: pointer; }
  button.ghost:hover { border-color: var(--axis); color: var(--ink); }

  /* Section nav — ten sections and ten thousand pixels, with nothing to click */
  nav.sections { position: sticky; top: 0; z-index: 6; display: flex; gap: 2px;
                 overflow-x: auto; padding: 8px 0; margin: 0 -4px 4px;
                 background: var(--page); border-bottom: 1px solid var(--border);
                 scrollbar-width: none; }
  nav.sections::-webkit-scrollbar { display: none; }
  nav.sections a { flex: none; font-size: 12px; color: var(--ink-2); text-decoration: none;
                   padding: 5px 10px; border-radius: 8px; white-space: nowrap;
                   display: flex; gap: 6px; align-items: center; }
  nav.sections a:hover { background: var(--heat-0); color: var(--ink); }
  nav.sections a[aria-current="true"] { color: var(--ink); background: var(--heat-0);
                                        font-weight: 500; }
  nav.sections .badge { font-size: 10px; font-variant-numeric: tabular-nums;
                        color: var(--muted); }
  section { scroll-margin-top: 56px; }

  /* Do this next */
  .actions { display: grid; gap: 2px; }
  .action-row { display: grid; grid-template-columns: 22px 1fr; gap: 12px;
                padding: 12px 0; border-top: 1px solid var(--border); }
  .action-row:first-child { border-top: none; }
  .action-n { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums;
              padding-top: 1px; }
  .action-title { font-size: 13.5px; font-weight: 600; line-height: 1.4; }
  .action-detail { font-size: 12px; color: var(--ink-2); margin-top: 3px; line-height: 1.5; }
  .action-link { font-size: 11px; color: var(--series-1); text-decoration: none;
                 margin-top: 5px; display: inline-block; }
  .action-link:hover { text-decoration: underline; }

  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
          padding: 20px; margin-top: 16px; }
  .card > h2 { font-size: 15px; font-weight: 600; margin: 0 0 2px; }
  .card > .sub { margin-bottom: 18px; max-width: 72ch; }
  .card-head { display: flex; flex-wrap: wrap; gap: 8px; align-items: flex-start;
               justify-content: space-between; margin-bottom: 14px; }

  /* Hero + tiles */
  .hero-row { display: flex; flex-wrap: wrap; gap: 32px; align-items: flex-end; }
  .hero-val { font-size: 52px; font-weight: 600; line-height: 1; letter-spacing: -0.02em; }
  .hero-label { color: var(--ink-2); font-size: 13px; margin-top: 8px; max-width: 34ch; }
  .delta { font-size: 13px; font-weight: 500; margin-top: 8px; display: flex;
           gap: 6px; align-items: center; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(118px, 1fr));
           gap: 20px 24px; flex: 1 1 320px; }
  .tile-label { color: var(--muted); font-size: 12px; }
  .tile-val { font-size: 21px; font-weight: 600; margin-top: 2px; }
  .tile-note { color: var(--muted); font-size: 11px; margin-top: 2px; }
  .driver { font-size: 12px; color: var(--ink-2); margin-top: 8px; max-width: 46ch;
            line-height: 1.5; }
  .driver b { color: var(--ink); font-weight: 600; }

  /* Charts */
  .plot { width: 100%; position: relative; }
  .plot svg { display: block; width: 100%; height: auto; overflow: visible; }
  .legend { display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 10px; }
  .legend-item { display: flex; gap: 7px; align-items: center; font-size: 12px;
                 color: var(--ink-2); }
  .key-line { width: 14px; height: 2px; border-radius: 1px; flex: none; }
  .key-box { width: 11px; height: 11px; border-radius: 2px; flex: none; }
  .note { color: var(--muted); font-size: 12px; margin-top: 14px; max-width: 78ch; }

  /* Quality strip */
  .strip-wrap { padding: 0 58px 0 40px; }    /* the line chart's own left/right margins */
  .strip { display: flex; gap: 2px; margin-top: 4px; align-items: flex-end; height: 17px; }
  @media (max-width: 560px) { .strip-wrap { padding: 0; } }
  .strip-cell { flex: 1; height: 6px; border-radius: 2px; background: var(--quality); }

  /* Heatmap */
  .heat-scroll { overflow-x: auto; margin: 0 -4px; padding: 0 4px 4px; }
  .heat { display: grid; gap: 2px; min-width: max-content; }
  .heat-label { font-size: 12px; color: var(--ink-2); padding-right: 12px;
                white-space: nowrap; display: flex; align-items: center; gap: 6px;
                position: sticky; left: 0; z-index: 1; background: var(--surface); }
  .heat-label .nm { overflow: hidden; text-overflow: ellipsis; min-width: 0; }
  @media (max-width: 780px) { .heat-label { max-width: 146px; } }
  .heat-date { font-size: 10px; color: var(--muted); text-align: center;
               font-variant-numeric: tabular-nums; }
  .cell { min-width: 24px; height: 22px; border-radius: 3px; background: var(--heat-0);
          cursor: default; }
  .cell[data-state="untested"] { background: none; box-shadow: inset 0 0 0 1px var(--hollow); }
  .cell[data-state="before"] { background: none; }
  .cell:hover, .cell:focus-visible { outline: 2px solid var(--ink); outline-offset: 1px; }
  .sev { font-size: 10px; color: var(--muted); font-variant-numeric: tabular-nums; flex: none; }

  /* Cards grid */
  .controls { display: flex; flex-wrap: wrap; gap: 14px; align-items: center;
              margin: 20px 0 4px; font-size: 13px; color: var(--ink-2); }
  .controls select, .controls label { font: inherit; color: inherit; }
  .controls select { background: var(--surface); color: var(--ink);
                     border: 1px solid var(--border); border-radius: 8px; padding: 4px 8px; }
  /* One expandable row per pattern. The collapsed row is the diagnosis, the
     detail is the evidence — previously two sections that listed the same
     the same names in the same order. */
  .row-toggle { background: none; border: 0; padding: 0; font: inherit; color: inherit;
                cursor: pointer; display: flex; gap: 6px; align-items: baseline;
                text-align: left; width: 100%; }
  .row-toggle:hover .pname { color: var(--series-1); }
  .caret { color: var(--muted); font-size: 9px; flex: none; }
  .row-toggle[aria-expanded="true"] .pname { font-weight: 600; }
  .pname { line-height: 1.4; }
  .row-ex { font-size: 11.5px; line-height: 1.4; margin-top: 4px; color: var(--muted);
            display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
            overflow: hidden; }
  .row-ex .right { color: var(--ink-2); font-weight: 500; }
  .row-ex .wrong { text-decoration: line-through; text-decoration-color: var(--hollow); }
  /* The table sets `white-space: nowrap` on every cell so the diagnosis columns
     stay on one line. The detail cell holds prose, and inheriting that made it
     one very long line, clipped at the card edge. */
  tr.detail-row > td { padding: 0 8px 26px 26px; border-bottom: 1px solid var(--grid);
                       white-space: normal; text-align: left; }
  .pdetail { max-width: 78ch; }
  .permalink { font-size: 11px; color: var(--muted); text-decoration: none;
               margin-top: 16px; display: inline-block; }
  .permalink:hover { color: var(--series-1); }
  #patterns tbody tr { scroll-margin-top: 64px; }
  #patterns tbody th[scope="row"] { min-width: 250px; }
  #patterns tbody tr:target > th, #patterns tbody tr:target > td { background: var(--heat-0); }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
  .chip { font-size: 11px; padding: 2px 7px; border-radius: 999px;
          border: 1px solid var(--border); color: var(--ink-2); display: flex;
          gap: 5px; align-items: center; }
  /* inline-block, not inline: outside a flex row a bare span ignores width */
  .dot { width: 7px; height: 7px; border-radius: 50%; flex: none; display: inline-block; }
  .mstats { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 12px; margin-top: 14px;
            font-size: 12px; }
  .mstats .k { color: var(--muted); }
  .mstats .v { font-weight: 500; font-variant-numeric: tabular-nums; margin-top: 1px; }
  details { margin-top: 12px; border-top: 1px solid var(--border); padding-top: 10px; }
  summary { font-size: 12px; color: var(--ink-2); cursor: pointer; }
  summary:hover { color: var(--ink); }

  /* An open card takes the whole grid row: at a third of the width its notes
     wrap to a very short measure, and its two neighbours stretch to match a
     tall row of mostly blank space. */
  .pdetail .prose, .pdetail .ex-list { max-width: 74ch; }

  /* Worked examples — the only part of a note you can practise from */
  .ex-list { display: grid; gap: 8px; margin: 2px 0 0; }
  .ex { font-size: 12.5px; line-height: 1.45; }
  .ex .wrong { color: var(--ink-2); text-decoration: line-through;
               text-decoration-color: var(--hollow); }
  .ex .arrow { color: var(--muted); margin: 0 6px; }
  .ex .right { color: var(--ink); font-weight: 500; }
  .ex .when { color: var(--muted); font-size: 11px; margin-left: 6px;
              font-variant-numeric: tabular-nums; }
  .note-head { font-size: 11px; color: var(--muted); margin: 16px 0 6px;
               text-transform: uppercase; letter-spacing: 0.04em; }
  .prose { font-size: 12.5px; line-height: 1.55; color: var(--ink-2); margin: 0 0 10px; }
  .prose code, .ex code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                          font-size: 0.92em; background: var(--heat-0);
                          padding: 0 4px; border-radius: 4px; }
  .prose strong { color: var(--ink); font-weight: 600; }
  .status { font-size: 12px; color: var(--ink-2); line-height: 1.5; }
  .decision { border-left: 2px solid var(--grid); padding-left: 10px; margin-top: 12px; }
  .decision .dt { font-size: 12px; font-weight: 600; color: var(--ink); line-height: 1.45; }

  /* Vocabulary */
  .vrow { display: grid; grid-template-columns: minmax(130px, 200px) 1fr auto;
          gap: 14px; align-items: center; padding: 11px 0;
          border-top: 1px solid var(--border); }
  .vrow:first-of-type { border-top: none; }
  .vphrase { font-size: 13px; font-weight: 600; }
  .vsub { font-size: 11px; color: var(--muted); margin-top: 3px; line-height: 1.4; }
  .vmove { font-size: 11px; display: flex; gap: 6px; align-items: center;
           justify-content: flex-end; white-space: nowrap; }
  .spark-cells { display: flex; gap: 2px; align-items: flex-end; height: 26px; }
  .spark-cells i { flex: 1; min-width: 4px; background: var(--series-1);
                   border-radius: 1px 1px 0 0; }
  .spark-cells i[data-zero="1"] { background: var(--grid); }

  /* Level */
  .lvl-head { display: flex; flex-wrap: wrap; gap: 32px; align-items: flex-end; }
  .lvl-val { font-size: 44px; font-weight: 600; line-height: 1; letter-spacing: -0.02em; }
  .lvl-note { color: var(--ink-2); font-size: 12px; margin-top: 8px; max-width: 48ch;
              line-height: 1.5; }
  .dims { display: grid; grid-template-columns: repeat(auto-fit, minmax(218px, 1fr));
          gap: 22px 26px; margin-top: 24px; }
  .dim-name { display: flex; gap: 10px; align-items: baseline;
              justify-content: space-between; font-size: 13px; font-weight: 600;
              border-bottom: 1px solid var(--border); padding-bottom: 6px;
              margin-bottom: 12px; }
  .dim-rung { font-size: 11px; font-weight: 500; color: var(--ink-2); display: flex;
              gap: 6px; align-items: center; white-space: nowrap; }
  .mrow { margin-bottom: 14px; }
  .mlab { font-size: 12px; color: var(--ink-2); display: flex; gap: 10px;
          justify-content: space-between; align-items: baseline; }
  .mval { font-variant-numeric: tabular-nums; color: var(--ink); font-weight: 600;
          flex: none; }
  .mneed { font-size: 11px; color: var(--muted); margin-top: 3px; }
  .mnote-s { font-size: 11px; color: var(--muted); line-height: 1.45; margin-top: 4px; }

  /* Timeline */
  a.report { color: var(--series-1); text-decoration: none; }
  a.report:hover { text-decoration: underline; }
  .tags { display: flex; flex-wrap: wrap; gap: 5px; }

  /* Horizontal bars */
  .bars { display: grid; gap: 6px; margin: 2px 0 4px; max-width: 520px; }
  .bar-row { display: grid; grid-template-columns: 96px 1fr 34px; gap: 10px;
             align-items: center; font-size: 12px; }
  .bar-label { color: var(--ink-2); text-align: right; }
  .bar-track { height: 14px; }
  .bar-track i { display: block; height: 100%; background: var(--series-1);
                 border-radius: 0 4px 4px 0; }
  .bar-val { font-variant-numeric: tabular-nums; font-weight: 600; }
  .bar-row:hover .bar-track i, .bar-row:focus-visible .bar-track i { filter: brightness(1.08); }

  /* Speech metrics */
  .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(215px, 1fr));
             gap: 22px 24px; margin-top: 2px; }
  .metric .mlabel { font-size: 12px; color: var(--muted); }
  .metric .val { font-size: 21px; font-weight: 600; margin-top: 1px; }
  .metric .unit { font-size: 12px; font-weight: 400; color: var(--ink-2); }
  .metric .mnote { font-size: 11px; color: var(--muted); margin-top: 8px; }
  .metric .delta-s { font-size: 11px; margin-top: 2px; display: flex; gap: 5px; }
  .meter { position: relative; height: 6px; border-radius: 3px; background: var(--heat-0);
           min-width: 84px; }
  .meter i { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 3px;
             background: var(--series-1); }
  .meter u { position: absolute; top: -3px; bottom: -3px; width: 1px;
             background: var(--axis); }

  /* Ladder */
  .rungs { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }
  .rung-def { font-size: 12px; color: var(--ink-2); flex: 1 1 200px; min-width: 180px;
              border-left: 2px solid var(--grid); padding-left: 10px; }
  .rung-def b { display: block; color: var(--ink); font-weight: 600; }
  .notice { border-left: 2px solid var(--warning); padding: 3px 0 3px 12px;
            margin: 0 0 18px; font-size: 12.5px; color: var(--ink-2); max-width: 82ch; }
  .chipbar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
  button.state { font: inherit; font-size: 12px; padding: 4px 10px; border-radius: 999px;
                 border: 1px solid var(--border); background: none; color: var(--ink-2);
                 cursor: pointer; display: flex; gap: 7px; align-items: center; }
  button.state:hover { border-color: var(--axis); color: var(--ink); }
  button.state[aria-pressed="true"] { border-color: var(--ink); color: var(--ink); }
  .count { font-variant-numeric: tabular-nums; font-weight: 600; }
  td.rung, th.rung, td.where, th.where { text-align: left; }
  td.where, th.where { white-space: normal; min-width: 200px; }
  tbody th[scope="row"] { white-space: normal; min-width: 190px; }
  #ladder td, #ladder th { padding: 7px 8px; vertical-align: top; }
  .cellrow { display: flex; gap: 7px; align-items: baseline; }
  .detail { color: var(--muted); font-size: 11px; }
  .overdue { color: var(--critical); }
  .action { color: var(--ink-2); }

  /* Tables */
  table { border-collapse: collapse; width: 100%; font-size: 12px;
          font-variant-numeric: tabular-nums; }
  caption { text-align: left; color: var(--muted); font-size: 12px; padding-bottom: 8px; }
  th, td { text-align: right; padding: 5px 8px; border-bottom: 1px solid var(--grid);
           white-space: nowrap; }
  th:first-child, td:first-child { text-align: left; }
  thead th { color: var(--muted); font-weight: 500; }
  .table-wrap { overflow-x: auto; }
  [hidden] { display: none !important; }

  /* View switch */
  .views { display: flex; gap: 2px; padding: 4px 0 0; }
  button.view { font: inherit; font-size: 13px; padding: 6px 14px; border-radius: 8px;
                border: 1px solid transparent; background: none; color: var(--muted);
                cursor: pointer; min-height: 36px; }
  button.view:hover { color: var(--ink); }
  button.view[aria-selected="true"] { color: var(--ink); font-weight: 600;
                                      border-color: var(--border);
                                      background: var(--surface); }

  /* The loop */
  .loopcard { padding: 16px 20px; }
  .loop { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; }
  .loop-side { border-left: 2px solid var(--border); padding-left: 12px; }
  .loop-side[data-state="stale"] { border-left-color: var(--state-stale); }
  .loop-side[data-state="warn"] { border-left-color: var(--state-warn); }
  .loop-side[data-state="ok"] { border-left-color: var(--state-ok); }
  .loop-head { display: flex; gap: 7px; align-items: center; }
  .loop-label { font-size: 13px; font-weight: 600; }
  .loop-state { font-size: 11px; color: var(--muted); }
  .loop-when { font-size: 18px; font-weight: 600; margin-top: 3px;
               font-variant-numeric: tabular-nums; }
  .loop-detail { font-size: 11.5px; color: var(--muted); margin-top: 2px; line-height: 1.45; }
  .loop-note { font-size: 12px; color: var(--ink-2); margin-top: 16px; line-height: 1.55;
               max-width: 84ch; border-top: 1px solid var(--border); padding-top: 12px; }

  /* Where you are */
  .where { display: flex; flex-wrap: wrap; gap: 36px; align-items: flex-start; }
  .where > div:first-child { flex: 1 1 280px; }
  .where-metric { flex: 1 1 300px; }
  /* Before the level is established the measurement leads and the level
     follows, so the first thing read is a number rather than its absence. */
  .where[data-established="false"] { flex-direction: row-reverse;
                                     justify-content: flex-end; }
  .where[data-established="false"] > div:first-child { flex: 0 1 280px; }
  .where-val { font-size: 40px; font-weight: 600; line-height: 1; letter-spacing: -0.02em; }
  .where-sub { color: var(--ink-2); font-size: 13px; margin-top: 8px; }
  .where-gap { font-size: 12px; color: var(--ink-2); margin-top: 14px; line-height: 1.55;
               max-width: 44ch; }
  .where-num { font-size: 32px; font-weight: 600; line-height: 1.1; margin-top: 2px; }
  .where-move { font-size: 12px; color: var(--ink-2); margin-top: 6px; }
  .where-alt { font-size: 11.5px; color: var(--muted); margin-top: 14px; line-height: 1.5;
               max-width: 52ch; border-top: 1px solid var(--border); padding-top: 10px; }

  /* The one thing to do */
  .lead { border-left: 3px solid var(--series-1); padding: 2px 0 2px 14px; }
  .lead[data-blocking="true"] { border-left-color: var(--state-stale); }
  .lead-eyebrow { font-size: 10.5px; color: var(--muted); text-transform: uppercase;
                  letter-spacing: 0.05em; }
  .lead-title { font-size: 17px; font-weight: 600; line-height: 1.35; margin-top: 5px; }
  .lead-detail { font-size: 13px; color: var(--ink-2); margin-top: 6px; line-height: 1.6;
                 max-width: 76ch; }
  details.more { border-top: 1px solid var(--border); margin-top: 20px; }

  /* Start-to-now */
  .cmp-wrap { border-top: 1px solid var(--border); margin-top: 22px; padding-top: 18px; }
  .sub-h { font-size: 13.5px; font-weight: 600; margin: 0 0 2px; }
  .cmp { display: grid; gap: 2px; margin-top: 14px; }
  .cmp-row { display: grid; grid-template-columns: 1fr auto 76px; gap: 16px;
             align-items: center; padding: 10px 0; border-top: 1px solid var(--border); }
  .cmp-row:first-child { border-top: none; }
  .cmp-label { font-size: 13px; font-weight: 500; }
  .cmp-note { font-size: 11px; color: var(--muted); margin-top: 2px; line-height: 1.45;
              max-width: 56ch; }
  .cmp-nums { font-size: 14px; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .cmp-from { color: var(--muted); }
  .cmp-arrow { color: var(--muted); margin: 0 5px; }
  .cmp-to { font-weight: 600; }
  .cmp-verdict { font-size: 13px; font-weight: 600; text-align: right;
                 font-variant-numeric: tabular-nums; }

  /* Focus slate */
  .slate { display: grid; gap: 2px; }
  .slate-row { display: grid; grid-template-columns: minmax(0, 1fr) 120px 172px; gap: 18px;
               align-items: center; padding: 13px 0; border-top: 1px solid var(--border); }
  .slate-row:first-child { border-top: none; }
  .slate-name { font-size: 13.5px; font-weight: 600; color: var(--ink);
                text-decoration: none; }
  .slate-name:hover { color: var(--series-1); }
  .slate-flags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
  .tier { font-size: 10.5px; color: var(--muted); }
  .tier-clarity { color: var(--series-2); }
  .flag { font-size: 10.5px; color: var(--muted); border: 1px solid var(--border);
          border-radius: 999px; padding: 0 6px; }
  .slate-why { font-size: 11.5px; color: var(--ink-2); margin-top: 5px; line-height: 1.5;
               max-width: 62ch; }
  .slate-spark { min-width: 0; }
  .slate-spark-line { overflow: hidden; }
  .spark-dir { font-size: 10.5px; font-weight: 500; margin-top: 3px; text-align: center; }
  .slate-do { text-align: right; }
  .slate-action { font-size: 12px; font-weight: 500; }
  .slate-impact { font-size: 11px; color: var(--muted); margin-top: 2px;
                  font-variant-numeric: tabular-nums; }

  /* Since you looked */
  .since-line { font-size: 15px; font-weight: 500; }

  /* About */
  .facts { display: grid; gap: 14px; margin-top: 4px; }
  .fact { border-left: 2px solid var(--grid); padding-left: 12px; }
  .fact-head { font-size: 13px; font-weight: 600; }
  .fact-body { font-size: 12px; color: var(--ink-2); margin-top: 3px; line-height: 1.55;
               max-width: 82ch; }

  /* Tooltip */
  .tip { position: fixed; z-index: 10; pointer-events: none; opacity: 0;
         transition: opacity .1s; background: var(--surface); color: var(--ink);
         border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px;
         font-size: 12px; box-shadow: 0 6px 24px rgba(0,0,0,.14); max-width: 260px; }
  .tip-head { color: var(--muted); font-size: 11px; margin-bottom: 4px; }
  .tip-row { display: flex; gap: 8px; align-items: baseline; }
  .tip-val { font-weight: 600; font-variant-numeric: tabular-nums; }
  .tip-name { color: var(--ink-2); }
  @media (prefers-reduced-motion: reduce) { .tip { transition: none; } }

  /* ---------------------------------------------------------------------
     Narrow screens. The page had two layout media queries in three hundred
     lines of stylesheet, a global `white-space: nowrap` on every cell, and a
     tile grid that produced three cramped columns at phone width. What matters
     most on a phone is the top of the Now view — the loop and the one thing to
     do — and what matters least is a per-session table, so the tables become
     card lists rather than horizontal scrollers: a table you have to drag
     sideways is one you do not read.
     --------------------------------------------------------------------- */
  @media (max-width: 860px) {
    .loop { grid-template-columns: 1fr; gap: 12px; }
    .slate-row { grid-template-columns: 1fr 72px; }
    .slate-do { grid-column: 1 / -1; text-align: left; display: flex; gap: 10px;
                align-items: baseline; }
  }

  @media (max-width: 600px) {
    body { padding: 0 16px 48px; }
    header { padding: 20px 0 4px; }
    .card { padding: 16px; border-radius: 10px; }
    .where { gap: 22px; }
    .where-val { font-size: 34px; }
    .where-num { font-size: 27px; }
    .lead-title { font-size: 15.5px; }
    .tiles, .dims, .metrics { grid-template-columns: 1fr; gap: 16px; }
    .cmp-row { grid-template-columns: 1fr auto; row-gap: 4px; }
    .cmp-verdict { grid-column: 2; text-align: right; }
    .bar-row { grid-template-columns: 76px 1fr 30px; }
    .vrow { grid-template-columns: 1fr; gap: 8px; }
    .vmove { justify-content: flex-start; }

    /* Tables become one card per row. The header text is carried on each cell
       by `data-label`, set where the row is built. */
    .table-wrap table, .table-wrap thead, .table-wrap tbody,
    .table-wrap tr, .table-wrap th, .table-wrap td { display: block; width: auto; }
    .table-wrap thead { display: none; }
    .table-wrap tr { border-bottom: 1px solid var(--border); padding: 10px 0; }
    .table-wrap th, .table-wrap td { border: none; padding: 2px 0; text-align: left;
                                     white-space: normal; }
    .table-wrap tbody th[scope="row"] { font-size: 13px; font-weight: 600;
                                        min-width: 0; margin-bottom: 4px; }
    .table-wrap td[data-label]::before { content: attr(data-label) " ";
                                         color: var(--muted); font-size: 11px; }
    .table-wrap td:empty { display: none; }

    /* The grid is one column per session and cannot usefully shrink; on a phone
       it is a drag-sideways object rather than a chart, so the panel says to
       open it elsewhere instead of pretending. */
    .heat-scroll { display: none; }
    .heat-small { display: block; }
  }
  .heat-small { display: none; font-size: 12px; color: var(--ink-2); line-height: 1.55; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>Spoken English progress</h1>
      <div class="sub" id="meta"></div>
    </div>
    <button class="ghost" id="theme" type="button">Theme</button>
  </header>
  <div class="views" role="tablist" aria-label="Views">
    <button class="view" id="view-now" role="tab" aria-selected="true"
            aria-controls="now" type="button">Now</button>
    <button class="view" id="view-evidence" role="tab" aria-selected="false"
            aria-controls="evidence" type="button">Evidence</button>
  </div>
  <nav class="sections" id="nav" aria-label="Sections"></nav>

  <div id="now" role="tabpanel" aria-labelledby="view-now">
    <section class="card loopcard" id="loop"></section>
    <section class="card" id="headline"></section>
    <section class="card" id="actions"></section>
    <section class="card" id="since" hidden></section>
    <section class="card" id="trend"></section>
    <section class="card" id="focus"></section>
    <section class="card" id="working"></section>
  </div>

  <div id="evidence" role="tabpanel" aria-labelledby="view-evidence" hidden>
    <section class="card" id="level"></section>
    <section class="card" id="patterns"></section>
    <section class="card" id="chances"></section>
    <section class="card" id="heatmap"></section>
    <section class="card" id="speech"></section>
    <section class="card" id="asking"></section>
    <section class="card" id="askpatterns"></section>
    <section class="card" id="vocabulary"></section>
    <section class="card" id="quality"></section>
    <section class="card" id="timeline"></section>
    <section class="card" id="about"></section>
  </div>
</div>
<script id="model" type="application/json">__MODEL_JSON__</script>
<script>
"use strict";
const MODEL = JSON.parse(document.getElementById("model").textContent);

const SECTION_LABELS = {
  loop: "The loop",
  headline: "Where you are",
  actions: "Do this next",
  since: "Since you looked",
  trend: "Is it working?",
  focus: "Focus",
  working: "What's working",
  level: "Level detail",
  patterns: "Every pattern",
  chances: "Chances",
  heatmap: "Session by session",
  speech: "How it was spoken",
  asking: "Asking questions",
  askpatterns: "Question patterns",
  vocabulary: "Words to retire",
  quality: "Reliability",
  timeline: "Timeline",
  about: "About this page",
};

// Which view each section lives in. The Now view is bounded — it must stay
// readable at session 12 and at session 300 — and everything that grows without
// limit lives in Evidence, which is navigated rather than scrolled past.
const VIEWS = {
  now: ["loop", "headline", "actions", "since", "trend", "focus", "working"],
  evidence: ["level", "patterns", "chances", "heatmap", "speech", "asking",
             "askpatterns", "vocabulary", "quality", "timeline", "about"],
};

/* ---------- helpers ---------- */
const NS = "http://www.w3.org/2000/svg";
const num = (v, d = 2) => v === null || v === undefined ? "\\u2014" : v.toFixed(d);
// Same number without the trailing zeros a fixed precision adds.
const trim = (v) => v === null || v === undefined ? "\\u2014"
  : String(parseFloat(v.toFixed(3)));
const int = (v) => v === null || v === undefined ? "\\u2014" : v.toLocaleString("en-US");
const shortDate = (d) => d.slice(5).replace("-", "/");
// Narrow enough for a season of column headers side by side: "8/3", not "08/03".
const tinyDate = (d) => `${+d.slice(5, 7)}/${+d.slice(8, 10)}`;

function el(tag, props = {}, kids = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === null || v === undefined) continue;
    if (k === "text") node.textContent = v;            // labels are untrusted data
    else if (k === "class") node.className = v;
    else if (k === "style") node.style.cssText = v;
    else if (k.startsWith("data") || k === "tabindex" || k === "hidden")
      node.setAttribute(k === "tabindex" ? "tabindex" : k, v);
    else node[k] = v;
  }
  for (const kid of [].concat(kids)) if (kid) node.append(kid);
  return node;
}
function svg(tag, attrs = {}) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs))
    if (v !== null && v !== undefined) node.setAttribute(k, v);
  return node;
}
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// How many rows a per-session table shows before it stops being a table and
// starts being an archive. Two tables on this page grow one row per session
// with no ceiling; at a hundred and fifty sessions they were 9,900px between
// them, more than half the page, and neither is a thing anyone makes a decision
// from — the decision-shaped readings are in the panels above.
const TABLE_ROWS = 12;

function moreRows(host, total, shown, what) {
  if (total <= shown) return;
  host.append(el("div", { class: "note", text:
    `Showing the ${shown} most recent of ${total} ${what}. The rest are in `
    + "analysis/, which is where they have always been \u2014 this page is for the "
    + "readings, not the archive." }));
}

// Carry each column's header onto its cells, so the narrow-screen card layout
// can print it. Done once over the finished table rather than at every call
// site: there are nine tables on this page and a `data-label` hand-written on
// each cell is nine places for one to go missing.
function labelCells(root) {
  for (const table of root.querySelectorAll("table")) {
    const heads = [...table.querySelectorAll("thead th")].map((h) => h.textContent.trim());
    if (!heads.length) continue;
    for (const row of table.querySelectorAll("tbody tr")) {
      [...row.children].forEach((cell, i) => {
        if (cell.tagName === "TD" && heads[i]) cell.setAttribute("data-label", heads[i]);
      });
    }
  }
  return root;
}

/* ---------- tooltip (one instance, shared) ---------- */
const tip = el("div", { class: "tip" });
document.body.append(tip);
function showTip(x, y, head, rows) {
  tip.textContent = "";
  tip.append(el("div", { class: "tip-head", text: head }));
  for (const row of rows) {
    const line = el("div", { class: "tip-row" });
    if (row.color) line.append(el("span", { class: "key-line", style: `background:${row.color}` }));
    line.append(el("span", { class: "tip-val", text: row.value }));
    if (row.name) line.append(el("span", { class: "tip-name", text: row.name }));
    tip.append(line);
  }
  tip.style.opacity = "1";
  const box = tip.getBoundingClientRect();
  const left = Math.min(Math.max(8, x + 14), window.innerWidth - box.width - 8);
  const top = Math.min(Math.max(8, y - box.height - 12), window.innerHeight - box.height - 8);
  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
}
const hideTip = () => { tip.style.opacity = "0"; };

/* ---------- axis ticks ---------- */
function ticks(max, count = 5) {
  if (!(max > 0)) return [0];
  const raw = max / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || 10 * mag;
  const out = [];
  const last = Math.ceil(max / step) * step;          // the top tick is >= the data, always
  for (let v = 0; v <= last + step * 0.001; v += step) out.push(Math.round(v * 100) / 100);
  return out;
}

/* ---------- responsive render ---------- */
// `min` is the floor a chart is still legible at. The default suits a full-width
// plot; a sparkline in a narrow table column needs a much lower one, and without
// it the drawing is wider than the cell holding it and lands on the text next
// door.
function responsive(host, draw, min = 240) {
  let width = 0;
  const run = () => {
    const w = Math.max(min, Math.floor(host.clientWidth));
    if (w === width) return;
    width = w;
    host.textContent = "";
    host.append(draw(w));
  };
  run();
  new ResizeObserver(run).observe(host);
}
</script>
<script>
/* ---------- the trend chart ---------- */

// Past this many sessions a per-session line stops being a trend and becomes a
// texture: every point is a handful of events in a couple of thousand words, and
// at a hundred and fifty of them the eye reads the noise as the signal. Above
// the threshold the raw series is kept but faded, and a rolling mean is drawn
// over it — the raw points stay because removing them would hide how much
// spread the mean is smoothing away.
const SMOOTH_ABOVE = 40;
const SMOOTH_WINDOW = 3;

function rollingMean(sessions, key, window = SMOOTH_WINDOW) {
  return sessions.map((_, i) => {
    const slice = sessions.slice(Math.max(0, i - window + 1), i + 1)
      .map((d) => d[key]).filter((v) => v !== null && v !== undefined);
    // A window with nothing measured in it stays a hole, exactly as the raw
    // series does — a smoothed line that bridges an untested session is
    // inventing the one thing this project is careful never to invent.
    return slice.length ? slice.reduce((a, b) => a + b, 0) / slice.length : null;
  });
}

function lineChart(width, sessions, series, opts = {}) {
  // A gutter under the axis for what was *done*, when there is anything to put
  // in it. Everything else on this page charts what happened; without a shared
  // axis the question the whole project exists to ask — did the practice change
  // the speech — cannot even be looked at.
  const events = opts.events || [];
  const gutter = events.length ? 26 : 0;
  const H = Math.max(210, Math.min(300, Math.round(width * 0.42))) + gutter;
  const M = { top: 14, right: 58, bottom: 30 + gutter, left: 40 };
  const iw = width - M.left - M.right;
  const ih = H - M.top - M.bottom;
  const values = series.flatMap((s) => sessions.map((d) => d[s.key])).filter((v) => v !== null);
  const scale = ticks(Math.max(...values, 1) * 1.08);
  const top = scale[scale.length - 1];
  const x = (i) => M.left + (sessions.length < 2 ? iw / 2 : (i / (sessions.length - 1)) * iw);
  const y = (v) => M.top + ih - (v / top) * ih;

  const root = svg("svg", { viewBox: `0 0 ${width} ${H}`, width, height: H,
                            role: "img" });

  for (const t of scale) {                                      // hairline, solid, recessive
    root.append(svg("line", { x1: M.left, x2: M.left + iw, y1: y(t), y2: y(t),
                              stroke: t === 0 ? css("--axis") : css("--grid"), "stroke-width": 1 }));
    root.append(Object.assign(svg("text", { x: M.left - 8, y: y(t) + 4, fill: css("--muted"),
                                            "font-size": 11, "text-anchor": "end",
                                            "font-variant-numeric": "tabular-nums" }),
                              { textContent: t }));
  }
  // Thin the x labels to whatever fits. At twelve sessions this is every other
  // one; at a hundred and fifty the old fixed step printed them on top of each
  // other until the axis was a solid black band.
  const every = Math.max(1, Math.ceil(sessions.length / Math.max(2, Math.floor(iw / 62))));
  sessions.forEach((s, i) => {
    if (i % every && i !== sessions.length - 1) return;
    root.append(Object.assign(svg("text", { x: x(i), y: H - 10, fill: css("--muted"),
                                            "font-size": 11, "text-anchor": "middle" }),
                              { textContent: shortDate(s.date) }));
  });

  // Above the threshold each series is drawn twice: the raw values faintly, and
  // a rolling mean as the line that carries the reading.
  const smoothing = sessions.length > SMOOTH_ABOVE && !opts.noSmoothing;
  const drawn = [];
  for (const s of series) {
    if (!smoothing) { drawn.push(s); continue; }
    const mean = rollingMean(sessions, s.key);
    const smoothKey = `${s.key}__mean`;
    sessions.forEach((d, i) => { d[smoothKey] = mean[i]; });
    drawn.push({ ...s, key: s.key, faded: true, noLabel: true });
    drawn.push({ ...s, key: smoothKey, label: `${s.label} (${SMOOTH_WINDOW}-session mean)` });
  }

  for (const s of drawn) {
    const color = css(s.token);
    let run = [];
    const flush = () => {
      if (run.length > 1)
        root.append(svg("path", { d: "M" + run.map((p) => `${p[0]},${p[1]}`).join("L"),
                                  fill: "none", stroke: color,
                                  "stroke-width": s.faded ? 1 : (s.dashed ? 1.5 : 2),
                                  "stroke-opacity": s.faded ? 0.22 : 1,
                                  "stroke-dasharray": s.dashed ? "4 3" : "",
                                  "stroke-linejoin": "round", "stroke-linecap": "round" }));
      else if (run.length === 1)
        root.append(svg("circle", { cx: run[0][0], cy: run[0][1], r: 2.5, fill: color }));
      run = [];
    };
    sessions.forEach((d, i) => {
      const v = d[s.key];
      if (v === null || v === undefined) flush(); else run.push([x(i), y(v)]);
    });
    flush();
    const last = sessions.reduce((best, d, i) =>
      (d[s.key] === null || d[s.key] === undefined ? best : i), -1);
    if (last >= 0 && !s.noLabel) {
      const lastValue = sessions[last][s.key];
      root.append(svg("circle", { cx: x(last), cy: y(lastValue), r: 4.5, fill: color,
                                  stroke: css("--surface"), "stroke-width": 2 }));
      // Direct end label, selective — and anchored at the end so a series that
      // stops in the middle of the chart does not write over the line after it.
      const atEdge = last === sessions.length - 1;
      root.append(Object.assign(
        svg("text", { x: x(last) + (atEdge ? 10 : 0), y: y(lastValue) - (atEdge ? -4 : 10),
                      fill: css("--ink"), "font-size": 12, "font-weight": 600,
                      "text-anchor": atEdge ? "start" : "middle" }),
        { textContent: lastValue.toFixed(opts.decimals ?? 1) }));
    }
  }

  if (gutter) {
    const byDate = new Map(sessions.map((d, i) => [d.date, i]));
    const base = M.top + ih;
    // Where a treatment date falls between two sessions, it is placed
    // proportionally rather than snapped to one: practice happens on days with
    // no recording, and snapping would draw it as if it had happened during a
    // session it did not.
    const place = (date) => {
      if (byDate.has(date)) return x(byDate.get(date));
      let before = -1;
      sessions.forEach((d, i) => { if (d.date < date) before = i; });
      if (before < 0) return x(0);
      if (before >= sessions.length - 1) return x(sessions.length - 1);
      const a = Date.parse(sessions[before].date), b = Date.parse(sessions[before + 1].date);
      const f = b === a ? 0 : (Date.parse(date) - a) / (b - a);
      return x(before) + (x(before + 1) - x(before)) * f;
    };
    for (const ev of events) {
      const px = place(ev.date);
      // Only the repetitions are treatment (rule 19); a drill measures the form.
      // Drawn at different weights so a run of drills cannot read as a month of
      // training.
      const solid = ev.treatment;
      root.append(svg("line", { x1: px, x2: px, y1: base + 8, y2: base + 8 + (solid ? 14 : 8),
                                stroke: css(solid ? "--ink-2" : "--axis"),
                                "stroke-width": solid ? 2 : 1 }));
      const hit = svg("rect", { x: px - 5, y: base + 6, width: 10, height: 18,
                                fill: "transparent", tabindex: 0 });
      const rows = [
        { value: String(ev.repetitions), name: "corrected repetitions \u2014 the treatment" },
        { value: String(ev.drills), name: "drill blocks" },
        { value: String(ev.sessions), name: "practice sessions" },
      ];
      const show = (e) => showTip(e.clientX ?? 0, e.clientY ?? 0, ev.date, rows);
      hit.addEventListener("pointermove", show);
      hit.addEventListener("focus", () => {
        const b = hit.getBoundingClientRect(); showTip(b.right, b.top, ev.date, rows);
      });
      hit.addEventListener("pointerleave", hideTip);
      hit.addEventListener("blur", hideTip);
      root.append(hit);
    }
  }

  const hair = svg("line", { y1: M.top, y2: M.top + ih, stroke: css("--axis"),
                             "stroke-width": 1, opacity: 0 });
  root.append(hair);
  sessions.forEach((d, i) => {                                   // the crosshair finds the X
    const half = sessions.length < 2 ? iw : iw / (sessions.length - 1) / 2;
    const band = svg("rect", { x: Math.max(M.left, x(i) - half), y: M.top,
                               width: Math.max(1, half * 2), height: ih,
                               fill: "transparent", tabindex: 0 });
    const show = (ev) => {
      hair.setAttribute("x1", x(i)); hair.setAttribute("x2", x(i));
      hair.setAttribute("opacity", 1);
      const box = root.getBoundingClientRect();
      const rows = series
        .filter((s) => d[s.key] !== null && d[s.key] !== undefined)
        .map((s) => ({
          color: css(s.token), value: num(d[s.key], opts.decimals ?? 2), name: s.label,
        }));
      for (const extra of (opts.extraRows ? opts.extraRows(d) : [])) rows.push(extra);
      showTip(ev.clientX ?? box.left + x(i), ev.clientY ?? box.top + M.top, d.date, rows);
    };
    band.addEventListener("pointermove", show);
    band.addEventListener("focus", show);
    band.addEventListener("pointerleave", () => { hair.setAttribute("opacity", 0); hideTip(); });
    band.addEventListener("blur", () => { hair.setAttribute("opacity", 0); hideTip(); });
    root.append(band);
  });
  return root;
}
</script>
<script>
/* ---------- heat scale ---------- */
// At or below this many instances, a session's rate is mostly noise.
const THIN_EVIDENCE = 2;

const BINS = [
  { max: 0.75, token: "--heat-1", label: "\\u2264 0.75" },
  { max: 1.5, token: "--heat-2", label: "0.75\\u20131.5" },
  { max: 3, token: "--heat-3", label: "1.5\\u20133" },
  { max: 6, token: "--heat-4", label: "3\\u20136" },
  { max: Infinity, token: "--heat-5", label: "> 6" },
];
const binOf = (rate) => BINS.find((b) => rate <= b.max) || BINS[BINS.length - 1];

function heatGrid(model) {
  const dates = model.dates;
  const grid = el("div", { class: "heat",
    style: `grid-template-columns: max-content repeat(${dates.length}, minmax(24px, 1fr))` });
  grid.append(el("div", { class: "heat-label" }));
  for (const d of dates) grid.append(el("div", { class: "heat-date", text: tinyDate(d) }));

  // One tab stop for the whole grid, arrow keys within it. Giving every cell
  // tabindex=0 puts the great majority of the page's focus stops inside this one
  // table — reaching the section below it then takes a press of Tab per cell.
  const cells = [];
  for (const cat of model.categories) {
    const label = el("div", { class: "heat-label", title: cat.category }, [
      el("span", { class: "sev", text: `s${cat.severity}` }),
      el("span", { class: "nm", text: cat.category }),
    ]);
    grid.append(label);
    const row = [];
    for (const point of cat.series) {
      // The first cell of the first row is the grid's single tab stop; `cells`
      // alone is still empty for every cell of that first row.
      const cell = el("div", { class: "cell",
                               tabindex: cells.length || row.length ? -1 : 0 });
      cell.setAttribute("role", "gridcell");
      cell.setAttribute("aria-label", `${cat.category}, ${point.date}, `
        + (point.state === "seen" ? `${point.rate} per 1,000 words`
          : point.state === "clean" ? "clean"
          : point.state === "untested" ? "never came up" : "not tracked yet"));
      row.push(cell);
      cell.dataset.state = point.state;
      if (point.state === "seen") {
        cell.style.background = `var(${binOf(point.rate).token})`;
        // Thin evidence, less ink. A cell built on one or two instances is a
        // different kind of number from one built on twenty, and colouring
        // them alike invites reading a gradient that is mostly chance.
        if (point.occurrences <= THIN_EVIDENCE) cell.style.opacity = "0.45";
      }
      else if (point.state === "clean") cell.style.background = "var(--heat-0)";
      const rows = point.state === "seen"
        ? [{ value: num(point.rate), name: "per 1,000 words" },
           { value: `${point.occurrences}\\u00d7`, name: `in ${int(point.reliable_words)} words` }]
        : [{ value: point.state === "clean" ? "0" : "\\u2014",
             name: point.state === "clean" ? "clean \\u2014 the structure came up and was right"
               : point.state === "untested" ? "never came up this session \\u2014 not measured"
               : "not tracked yet" }];
      const show = (ev) => showTip(ev.clientX ?? 0, ev.clientY ?? 0,
                                   `${cat.category} \\u00b7 ${point.date}`, rows);
      cell.addEventListener("pointermove", show);
      cell.addEventListener("focus", (ev) => {
        const b = cell.getBoundingClientRect();
        showTip(b.right, b.top, `${cat.category} \\u00b7 ${point.date}`, rows);
      });
      cell.addEventListener("pointerleave", hideTip);
      cell.addEventListener("blur", hideTip);
      grid.append(cell);
    }
    cells.push(row);
  }

  const MOVES = {
    ArrowRight: [0, 1], ArrowLeft: [0, -1], ArrowDown: [1, 0], ArrowUp: [-1, 0],
  };
  grid.setAttribute("role", "grid");
  grid.setAttribute("aria-label", "Mistake rate by category and session");
  grid.addEventListener("keydown", (event) => {
    const move = MOVES[event.key];
    const home = event.key === "Home", end = event.key === "End";
    if (!move && !home && !end) return;
    let position = null;
    cells.forEach((row, y) => {
      const x = row.indexOf(document.activeElement);
      if (x >= 0) position = [y, x];
    });
    if (!position) return;
    const [y, x] = position;
    const target = home ? [y, 0] : end ? [y, cells[y].length - 1] : [y + move[0], x + move[1]];
    const next = (cells[target[0]] || [])[target[1]];
    if (!next) return;
    event.preventDefault();
    document.activeElement.setAttribute("tabindex", "-1");
    next.setAttribute("tabindex", "0");
    next.focus();
  });
  return grid;
}

function heatTable(model) {
  const table = el("table");
  table.append(el("caption", { text:
    "Rate per 1,000 reliable words. \\u201c0\\u201d = the structure came up and was right; "
    + "\\u201c\\u2014\\u201d = it never came up, so nothing was measured." }));
  const head = el("tr", {}, [el("th", { text: "Mistake" })]);
  for (const d of model.dates) head.append(el("th", { text: tinyDate(d) }));
  table.append(el("thead", {}, [head]));
  const body = el("tbody");
  for (const cat of model.categories) {
    const tr = el("tr", {}, [el("th", { scope: "row", text: cat.category })]);
    for (const p of cat.series)
      tr.append(el("td", { text: p.state === "seen" ? num(p.rate)
                                 : p.state === "clean" ? "0" : "\\u2014" }));
    body.append(tr);
  }
  table.append(body);
  return el("div", { class: "table-wrap" }, [table]);
}
</script>
<script>
/* ---------- sparkline for one category ---------- */
function sparkline(width, cat, top, height = 36) {
  const H = height, pad = 3;
  const points = cat.series;
  const x = (i) => pad + (points.length < 2 ? 0 : (i / (points.length - 1)) * (width - pad * 2));
  const y = (v) => H - pad - (top > 0 ? (v / top) * (H - pad * 2) : 0);
  const root = svg("svg", { viewBox: `0 0 ${width} ${H}`, width, height: H,
                            "aria-hidden": "true" });
  root.append(svg("line", { x1: 0, x2: width, y1: H - pad, y2: H - pad,
                            stroke: css("--grid"), "stroke-width": 1 }));
  const color = css("--series-1");
  let run = [];
  const flush = () => {
    if (run.length > 1)
      root.append(svg("path", { d: "M" + run.map((p) => `${p[0]},${p[1]}`).join("L"),
                                fill: "none", stroke: color, "stroke-width": 2,
                                "stroke-linejoin": "round", "stroke-linecap": "round" }));
    else if (run.length === 1)
      root.append(svg("circle", { cx: run[0][0], cy: run[0][1], r: 2, fill: color }));
    run = [];
  };
  points.forEach((p, i) => {
    if (p.state === "seen") run.push([x(i), y(p.rate)]);
    else if (p.state === "clean") { run.push([x(i), y(0)]); }
    else flush();                                   // untested breaks the line, never a zero
  });
  flush();
  const lastSeen = [...points].reverse().find((p) => p.state === "seen" || p.state === "clean");
  if (lastSeen) {
    const i = points.lastIndexOf(lastSeen);
    root.append(svg("circle", { cx: x(i), cy: y(lastSeen.state === "seen" ? lastSeen.rate : 0),
                                r: 4, fill: color, stroke: css("--surface"),
                                "stroke-width": 2 }));
  }
  return root;
}

/* memory.md is written for a person, so it carries inline markdown. Rendered as
   preformatted text it showed the syntax instead, asterisks and backticks and
   all.
   Tokenised into real elements — and every piece of content set with
   textContent, never innerHTML, because this is the owner's own prose and the
   page's rule is that text is data. */
function inlineMarkdown(text) {
  const frag = document.createDocumentFragment();
  const pattern = /\\*\\*([^*]+)\\*\\*|`([^`]+)`|(?<![\\w*])\\*([^*\\n]+)\\*(?![\\w*])/g;
  let last = 0, match;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) frag.append(document.createTextNode(text.slice(last, match.index)));
    const [tag, body] = match[1] !== undefined ? ["strong", match[1]]
      : match[2] !== undefined ? ["code", match[2]]
      : ["em", match[3]];
    const node = document.createElement(tag);
    node.textContent = body;
    frag.append(node);
    last = pattern.lastIndex;
  }
  if (last < text.length) frag.append(document.createTextNode(text.slice(last)));
  return frag;
}

function prose(text, cls = "prose") {
  const node = el("div", { class: cls });
  node.append(inlineMarkdown(text));
  return node;
}

function example(ex) {
  const row = el("div", { class: "ex" });
  row.append(el("span", { class: "wrong", text: ex.wrong }));
  row.append(el("span", { class: "arrow", text: "\\u2192" }));
  const right = el("span", { class: "right" });
  right.append(inlineMarkdown(ex.right));       // corrections carry **emphasis**
  row.append(right);
  if (ex.date) row.append(el("span", { class: "when",
    text: ex.source ? `${ex.date} \\u00b7 ${ex.source}` : ex.date }));
  return row;
}

function noteBlock(note) {
  const body = el("div");
  if (note.examples.length) {
    body.append(el("div", { class: "note-head", text: "Examples" }));
    body.append(el("div", { class: "ex-list" }, note.examples.map(example)));
  }
  // Status carries the one thing the CSV does not: the rule-18 `!` flag and
  // what was decided about it. The other four header fields are the card's own
  // numbers retold in prose, and are left out — see `_parse_note`.
  if (note.status) {
    body.append(el("div", { class: "note-head", text: "Status" }));
    body.append(prose(note.status, "status"));
  }
  if (note.notes || note.rest.length) {
    body.append(el("div", { class: "note-head", text: "Notes" }));
    if (note.notes) body.append(prose(note.notes));
    for (const paragraph of note.rest) body.append(prose(paragraph));
  }
  if (note.decisions.length) {
    const history = el("details", { style: "border-top:none;margin-top:6px" }, [
      el("summary", { text: `Changes of approach (${note.decisions.length})` }),
    ]);
    for (const decision of note.decisions) {
      const block = el("div", { class: "decision" });
      const title = el("div", { class: "dt" });
      title.append(inlineMarkdown(decision.title));
      block.append(title);
      if (decision.body) block.append(prose(decision.body));
      history.append(block);
    }
    body.append(history);
  }
  return body;
}

const DIRECTION = {
  improving: { token: "--good", text: "improving" },
  worsening: { token: "--critical", text: "worsening" },
  steady: { token: "--muted", text: "steady" },
  "n/a": { token: "--muted", text: "too few sessions" },
  // The rate moved, but on these counts the move cannot be told from chance.
  // Colouring it green or red would be picking a side of a coin flip.
  "not separable yet": { token: "--muted", text: "too few instances to tell" },
};

function patternDetail(cat) {
  const body = el("div", { class: "pdetail" });

  // The chart is scaled to this pattern alone. Shared across every pattern it
  // takes its scale from the worst of them, which draws all the rest as
  // near-straight lines along the baseline.
  const own = Math.max(...cat.series.filter((p) => p.state === "seen")
    .map((p) => p.rate), 0) || 1;
  const plot = el("div", { class: "plot", style: "max-width:560px" });
  body.append(plot);
  responsive(plot, (w) => sparkline(w, cat, own, 96));
  body.append(el("div", { class: "detail", style: "margin-top:2px",
    text: `scaled to this pattern's own range, 0 to ${num(own)} per 1,000 words` }));

  const stat = (label, value) => el("div", {}, [
    el("div", { class: "k", text: label }), el("div", { class: "v", text: value }),
  ]);
  const stats = el("div", { class: "mstats" }, [
    stat("Latest rate", cat.latest_rate === null ? "not measured"
      : num(cat.latest_rate) + (cat.latest_count ? ` (${cat.latest_count} instances)` : "")),
    stat("Impact", num(cat.impact)),
    stat("Tier", `severity ${cat.severity} \u00b7 ${cat.tier}`),
    stat("Recency-weighted rate", num(cat.weighted_rate)),
    stat("Measured in", `${cat.sessions_measured} of `
      + `${cat.series.filter((p) => p.state !== "before").length} sessions`),
    stat("First seen", cat.first_seen),
    stat("Last seen", cat.last_seen || "never"),
  ]);
  if (cat.drill) {
    stats.append(stat("Drill blocks", `${cat.drill.attempts}, last ${cat.drill.last_date}`));
    stats.append(stat("Drill accuracy", cat.drill.accuracy === null ? "\u2014"
      : `${Math.round(cat.drill.accuracy * 100)}% `
        + `(${cat.drill.correct}/${cat.drill.attempted})`));
  }
  body.append(stats);

  if (cat.note) body.append(noteBlock(cat.note));
  body.append(el("a", { class: "permalink", href: `#${cat.slug}`,
                        text: "\u00b6 link to this pattern" }));
  return body;
}
</script>
<script>
/* ---------- page ---------- */
const H = MODEL.headline;
document.getElementById("meta").textContent =
  `${H.sessions} sessions \\u00b7 ${H.first_date} \\u2192 ${H.last_date} `
  + `\\u00b7 built ${MODEL.generated_full}`;

/* the loop — is the machine that improves this actually running? */
(() => {
  const host = document.getElementById("loop");
  const L = MODEL.loop;
  if (!L || !L.sides) { host.hidden = true; return; }

  const WORDS = {
    ok: "running", warn: "behind", stale: "stopped", never: "never started",
  };
  const strip = el("div", { class: "loop" });
  for (const side of L.sides) {
    const elapsed = side.days === null ? "—"
      : side.days === 0 ? "today"
      : `${side.days} day${side.days === 1 ? "" : "s"} ago`;
    strip.append(el("div", { class: "loop-side", "data-state": side.state }, [
      el("div", { class: "loop-head" }, [
        // Never colour alone: the state is in the word as well as the dot.
        el("span", { class: "dot", style: `background: var(--state-${side.state})` }),
        el("span", { class: "loop-label", text: side.label }),
        el("span", { class: "loop-state", text: WORDS[side.state] }),
      ]),
      el("div", { class: "loop-when", text: elapsed }),
      el("div", { class: "loop-detail", text: side.detail }),
    ]));
  }
  host.append(strip);

  const notes = [];
  if (L.instrument_ahead) notes.push(
    `${L.recordings_in_window} recording(s) and ${L.sessions_in_window} practice session(s) `
    + `in the last ${L.window_days} days, with ${L.repetitions_in_window} corrected `
    + "repetition(s) in them. The recording measures and only the repetitions train "
    + "(rule 19), so more recordings do not improve the measurement — they consume the "
    + "time the practice needed.");
  const cad = L.cadence || {};
  if (cad.direction === "lengthening") notes.push(
    `Recordings are getting further apart: every ${cad.median} days across the record, `
    + `every ${cad.recent} lately.`);
  if (notes.length) host.append(el("div", { class: "loop-note", text: notes.join(" ") }));
})();

/* where you are */
(() => {
  const host = document.getElementById("headline");
  const G = MODEL.level_gap || {};
  const cur = MODEL.level.current || {};
  const clarity = MODEL.sessions.length
    ? MODEL.sessions[MODEL.sessions.length - 1].clarity_rate : null;

  // How the clarity tier has moved over the sessions the eye can hold, counted
  // rather than described: "up in 4 of the last 5" is a fact, "rising" is a
  // reading of one.
  const recent = MODEL.sessions.slice(-6).map((s) => s.clarity_rate).filter((v) => v !== null);
  let clarityNote = "";
  let clarityWorse = null;
  if (recent.length >= 3) {
    // Counted in both directions rather than one subtracted from the other: a
    // session that did not move the rate is neither, and inferring the falls
    // from the rises would quietly report those as falls.
    let up = 0, down = 0;
    for (let i = 1; i < recent.length; i += 1) {
      if (recent[i] > recent[i - 1]) up += 1;
      else if (recent[i] < recent[i - 1]) down += 1;
    }
    const worse = up > down;
    clarityWorse = worse;
    // The number printed has to be the number of the direction named. Printing
    // `up` under either label said "1 of the last 5 sessions moved it down" on
    // a stretch where one session moved it up and four moved it down.
    const moved = worse ? up : down;
    const steps = recent.length - 1;
    clarityNote = `${worse ? "▲" : "▼"} ${moved} of the last ${steps} `
      + `session${steps === 1 ? "" : "s"} moved it ${worse ? "up" : "down"}`;
  }

  // A level needs three qualifying sessions before it says anything, and until
  // then the largest element on the page was the words "not yet established" —
  // a new reader's first impression being a statement of absence. Below that
  // bar the two swap places: the clarity rate is a real measurement from the
  // first session, and the level waits its turn in small type.
  const established = cur.index !== null && cur.index !== undefined;
  host.append(el("div", { class: "where", "data-established": String(established) }, [
    el("div", {}, [
      el("div", { class: established ? "where-val" : "where-sub",
                  text: cur.label || H.cefr || "—" }),
      el("div", { class: "where-sub", text: !established
        ? `spoken level — the scale needs ${MODEL.level.promotion_sessions} qualifying `
          + `sessions before it will name one, and there are ${MODEL.sessions.length}`
        : `spoken level · rung ${cur.index + 1} of ${MODEL.level.scale.length}`
          + (MODEL.level.target ? ` · next is ${MODEL.level.target.label}` : "") }),
      // The rung is deliberately slow — three qualifying sessions — so on its own
      // it is the same word every week. The nearest unmet threshold is the part
      // that moves, and the part anything can be done about.
      G.measure ? el("div", { class: "where-gap" }, [
        el("span", { text: "Closest to " }),
        el("b", { text: G.target }),
        el("span", { text: `: ${G.measure.toLowerCase()} at ` }),
        el("b", { text: trim(G.value) }),
        el("span", { text: `, needs ${G.lower_is_better ? "≤" : "≥"} `
          + `${trim(G.threshold)} — ${Math.round(G.progress * 100)}% of the way` }),
        el("div", { class: "meter", style: "margin-top:7px;max-width:220px" }, [
          el("i", { style: `width:${Math.round(G.progress * 100)}%` }),
        ]),
      ]) : null,
    ]),
    el("div", { class: "where-metric" }, [
      el("div", { class: "tile-label", text: "Clarity-tier errors" }),
      el("div", { class: established ? "where-num" : "where-val", text: num(clarity) }),
      el("div", { class: "tile-note",
        text: "per 1,000 reliable words — the errors that cost the listener the meaning" }),
      // Colour, not just an arrow: this is the first number on the page, and
      // everywhere else on this page an up/down for an error rate is coloured
      // --critical/--good. Left plain here, it was the one hero figure that
      // didn't say at a glance whether it was good or bad news.
      clarityNote ? el("div", { class: "where-move",
        style: clarityWorse === null ? "" : `color: var(${clarityWorse ? "--critical" : "--good"})`,
        text: clarityNote }) : null,
      // The all-categories rate is kept, demoted, and labelled — it is the
      // number that used to lead, and it can be green on a session the clarity
      // tier got worse in.
      el("div", { class: "where-alt", text:
        `All tracked categories: ${num(H.rate)} per 1,000 on ${H.rate_date}. `
        + "That total rises as coaching finds new patterns, so it is not comparable "
        + "with itself over months — the chart below has the series that is." }),
    ]),
  ]));
})();

/* do this next */
(() => {
  const host = document.getElementById("actions");
  if (!MODEL.actions.length) { host.hidden = true; return; }
  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "Do this next" }),
      el("div", { class: "sub", text:
        "Nothing new here — this is the crossing of the rung a pattern fails on, its "
        + "impact ranking and what the schedule says is late, which otherwise means reading "
        + "three sections against each other. Every line says where it came from." }),
    ]),
  ]));

  // The first one is drawn differently on purpose. Rule 20: at conversational
  // speed the number of things anyone can consciously monitor is one, so a list
  // of five equal-weight items is a list of zero. The rest are there to be
  // glanced at, not carried.
  const [first, ...rest] = MODEL.actions;
  host.append(el("div", { class: "lead", "data-blocking": String(!!first.blocking) }, [
    el("div", { class: "lead-eyebrow",
      text: first.blocking ? "Before anything below this means much"
                           : "One thing, not five" }),
    el("div", { class: "lead-title", text: first.title }),
    el("div", { class: "lead-detail", text: first.detail }),
    el("a", { class: "action-link", href: `#${first.anchor}`,
              text: `↓ ${SECTION_LABELS[first.anchor] || first.anchor}` }),
  ]));

  if (!rest.length) return;
  const more = el("details", { class: "more" }, [
    el("summary", { text: `${rest.length} more, in priority order` }),
  ]);
  const list = el("div", { class: "actions" });
  rest.forEach((action, index) => {
    list.append(el("div", { class: "action-row" }, [
      el("div", { class: "action-n", text: String(index + 2) }),
      el("div", {}, [
        el("div", { class: "action-title", text: action.title }),
        el("div", { class: "action-detail", text: action.detail }),
        el("a", { class: "action-link", href: `#${action.anchor}`,
                  text: `↓ ${SECTION_LABELS[action.anchor] || action.anchor}` }),
      ]),
    ]));
  });
  more.append(list);
  host.append(more);
})();

/* since you last looked — the page is built on demand, so the realistic reader
   is weeks stale and "what changed" is a different question from "what is" */
(() => {
  const host = document.getElementById("since");
  const KEY = "vge-last-seen";
  let seen = null;
  try { seen = localStorage.getItem(KEY); } catch (e) { /* private window: no memory */ }
  try { localStorage.setItem(KEY, MODEL.generated_at); } catch (e) { /* no-op */ }

  // First visit, or a page built the same day it was last read: nothing to say,
  // and an empty "nothing changed" block is worse than no block.
  if (!seen || seen >= MODEL.generated_at) return;

  const fresh = MODEL.sessions.filter((s) => s.date > seen);
  const practice = MODEL.timeline.filter((r) => r.date > seen && r.practice_sessions);
  if (!fresh.length && !practice.length) return;

  const days = Math.round((Date.parse(MODEL.generated_at) - Date.parse(seen)) / 86400000);
  host.hidden = false;
  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "Since you last looked" }),
      el("div", { class: "sub", text: `${days} day${days === 1 ? "" : "s"} ago, `
        + `on ${seen}. This block is the only thing on the page your browser remembers; `
        + "it never leaves this device." }),
    ]),
  ]));

  const bits = [];
  if (fresh.length) bits.push(`${fresh.length} session${fresh.length === 1 ? "" : "s"} analysed`);
  if (practice.length) bits.push(`${practice.length} practice day${practice.length === 1 ? "" : "s"}`);
  host.append(el("div", { class: "since-line", text: bits.join(" · ") }));

  // Which patterns actually changed state, not just which numbers moved.
  const moved = MODEL.categories.filter((c) => {
    const points = c.series.filter((pt) => pt.date > seen && pt.rate !== null);
    return points.length && points.some((pt) => pt.rate > 0);
  }).slice(0, 4);
  if (moved.length) host.append(el("div", { class: "note", text:
    "Seen again since then: " + moved.map((c) => c.category).join(", ") }));
})();

/* trend */
(() => {
  const host = document.getElementById("trend");
  // Clarity against polish, not one total. The total is dominated by whichever
  // category happens to be most frequent, and that can be a severity-2 one; the
  // clarity tier is the part that costs the listener the meaning, and it is
  // what decides whether the speaker is getting easier to understand.
  const series = [
    { key: "clarity_rate", token: "--series-2",
      label: "clarity tier — costs the listener the meaning" },
    { key: "polish_rate", token: "--series-1",
      label: "polish tier — understood, just not native" },
    // Promoted out of the table view, where it was a column of numbers nobody
    // opened. It is the one series on this page that is comparable end to end:
    // the others grow as coaching finds categories, this one counts the same
    // five at both ends.
    { key: "cohort_rate", token: "--hollow", dashed: true,
      label: "day-one categories — the comparable one" },
  ];
  const words = MODEL.sessions.map((s) => s.reliable_words).filter(Boolean);
  const plot = el("div", { class: "plot" });
  const table = el("div", { hidden: "" });
  const toggle = el("button", { class: "ghost", type: "button", text: "Table view" });

  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "Is it working?" }),
      el("div", { class: "sub", text:
        "Occurrences per 1,000 reliable words, against what was actually trained. Read the "
        + "orange line first: those are the errors that cost a listener the meaning. The "
        + "grey line is the day-one categories \u2014 the only set counted the same way at "
        + "both ends of the history, and so the only one that can answer \u201cam I better "
        + "than when I started\u201d. Marks below the axis are drills and practice "
        + "sessions." }),
    ]),
    toggle,
  ]));
  const chartSide = el("div", {});
  host.append(chartSide);
  chartSide.append(el("div", { class: "legend" }, series.map((s) =>
    el("div", { class: "legend-item" }, [
      el("span", { class: "key-line", style: `background: var(${s.token})` }),
      el("span", { text: s.label }),
    ]))));
  chartSide.append(plot);
  chartSide.append(el("div", {}, [
    el("div", { class: "legend", style: "margin:12px 0 2px" }, [
      el("div", { class: "legend-item" }, [
        el("span", { class: "key-box", style: "background: var(--quality)" }),
        el("span", { text: "share of words whisper was unsure of \\u2014 taller is worse" }),
      ]),
    ]),
    (() => {
      const strip = el("div", { class: "strip" });
      const quality = new Map(MODEL.speech.sessions.map((q) => [q.date, q]));
      for (const s of MODEL.sessions) {
        // The WORD share, not the line share: a two-word "Yeah." weighs as much
        // as a full sentence by line, and that is where whisper is least sure.
        // fluency.warn_if_unreliable fires on this one for the same reason.
        const q = quality.get(s.date);
        const share = q ? q.word_share : null;
        const cell = el("div", { class: "strip-cell", tabindex: 0,
          style: `height:${share === null ? 2 : 3 + Math.round(share * 34)}px` });
        const rows = [
          { value: share === null ? "\\u2014" : `${Math.round(share * 100)}%`,
            name: "of words were low-confidence" },
          { value: q && q.line_share !== null ? `${Math.round(q.line_share * 100)}%` : "\\u2014",
            name: "of lines \\u2014 the weaker reading" },
          { value: int(s.reliable_words), name: "reliable words" },
          { value: s.mode || "\\u2014", name: "run mode" },
        ];
        const show = (ev) => showTip(ev.clientX ?? 0, ev.clientY ?? 0, s.date, rows);
        cell.addEventListener("pointermove", show);
        cell.addEventListener("focus", () => {
          const b = cell.getBoundingClientRect(); showTip(b.right, b.top, s.date, rows);
        });
        cell.addEventListener("pointerleave", hideTip);
        cell.addEventListener("blur", hideTip);
        strip.append(cell);
      }
      return el("div", { class: "strip-wrap" }, [strip]);
    })(),
  ]));
  if (MODEL.sessions.length > SMOOTH_ABOVE) chartSide.append(el("div", { class: "note", text:
    `Over ${SMOOTH_ABOVE} sessions, so the bold lines are a ${SMOOTH_WINDOW}-session rolling `
    + "mean and the faint ones behind them are the sessions themselves. Each single session "
    + "is a handful of events in a couple of thousand words; drawn alone at this length the "
    + "spread reads as the trend." }));

  const E = MODEL.exposure || {};
  // This is the statistical case FOR the chart above (why dividing by words is
  // fair, or isn't), not a reading of what it shows — a first glance at "is my
  // English improving" shouldn't have to clear a paragraph of correlation
  // coefficients to get to the answer below. Collapsed, not deleted: the case
  // still has to be checkable, just not mandatory reading on every visit.
  host.append(el("details", {}, [
    el("summary", { text: "Why divide by words spoken? (the statistical case)" }),
    el("div", { class: "note", text:
      `Sessions range from ${int(Math.min(...words))} to ${int(Math.max(...words))} reliable `
      + "words, and every figure here divides by that. Whether it should is testable, and the "
      + `answer on this history is: ${E.verdict || "not enough sessions to tell yet"}.`
      + (E.within_category !== null && E.within_category !== undefined
         ? ` Within a category, instances against words spoken correlate ${num(E.within_category)};`
           + ` the rate against words spoken, ${num(E.rate_vs_words)}.` : "")
      + (E.total_vs_categories !== null && E.total_vs_categories !== undefined
         ? ` The session total tracks the number of categories being looked for`
           + ` (${num(E.total_vs_categories)}) more closely than it tracks anything said,`
           + " so the all-categories total is partly a measure of attention; the table view"
           + " keeps the day-one cohort, which counts the same categories at both ends."
         : "")
      + (E.narrow ? ` Session lengths span only ${E.spread}× so far, narrow enough to hide a`
                    + " real relationship — python -m voxlib.exposure re-runs this as more"
                    + " sessions accumulate." : "") }),
  ]));
  host.append(table);

  responsive(plot, (w) => lineChart(w, MODEL.sessions, series, {
    events: MODEL.treatment || [],
    extraRows: (d) => [
      { value: num(d.rate), name: "both tiers together" },
      { value: `${d.clarity_count} + ${d.polish_count}`, name: "instances, clarity + polish" },
      { value: int(d.reliable_words), name: "reliable words" },
      { value: String(d.categories_tracked), name: "categories tracked" },
    ],
  }));

  toggle.addEventListener("click", () => {
    const showTable = chartSide.hidden;
    chartSide.hidden = !showTable;
    table.hidden = showTable;
    toggle.textContent = showTable ? "Table view" : "Chart view";
    if (!table.hidden && !table.dataset.built) {
      table.dataset.built = "1";
      const t = el("table");
      t.append(el("thead", {}, [el("tr", {}, [
        el("th", { text: "Session" }), el("th", { text: "Clarity" }),
        el("th", { text: "Polish" }), el("th", { text: "All tracked" }),
        el("th", { text: "Day-one categories" }), el("th", { text: "Occurrences" }),
        el("th", { text: "Reliable words" }), el("th", { text: "Categories" }),
        el("th", { text: "Low-confidence lines" }),
      ])]));
      const body = el("tbody");
      for (const s of MODEL.sessions) body.append(el("tr", {}, [
        el("th", { scope: "row", text: s.date }),
        el("td", { text: `${num(s.clarity_rate)} (${s.clarity_count})` }),
        el("td", { text: `${num(s.polish_rate)} (${s.polish_count})` }),
        el("td", { text: num(s.rate) }), el("td", { text: num(s.cohort_rate) }),
        el("td", { text: String(s.occurrences) }), el("td", { text: int(s.reliable_words) }),
        el("td", { text: `${s.categories_measured}/${s.categories_tracked} measured` }),
        el("td", { text: s.low_confidence_share === null ? "\\u2014"
          : `${Math.round(s.low_confidence_share * 100)}%` }),
      ]));
      t.append(body);
      table.append(el("div", { class: "table-wrap" }, [t]));
    }
  });
})();

/* am I better than when I started? */
(() => {
  const host = document.getElementById("trend");
  const P = MODEL.progress || {};
  if (!P.comparable) {
    host.append(el("div", { class: "note", text:
      `Two windows of ${P.window || 3} sessions are needed before a start-to-now comparison `
      + `means anything; there ${P.sessions === 1 ? "is" : "are"} ${P.sessions || 0} session`
      + `${P.sessions === 1 ? "" : "s"} on record.` }));
    return;
  }

  const rows = el("div", { class: "cmp" });
  for (const s of P.series) {
    const known = s.change !== null;
    rows.append(el("div", { class: "cmp-row", "data-key": s.key }, [
      el("div", {}, [
        el("div", { class: "cmp-label", text: s.label }),
        el("div", { class: "cmp-note", text: s.note }),
      ]),
      el("div", { class: "cmp-nums" }, [
        el("span", { class: "cmp-from", text: num(s.before) }),
        el("span", { class: "cmp-arrow", text: "→" }),
        el("span", { class: "cmp-to", text: num(s.after) }),
      ]),
      el("div", { class: "cmp-verdict",
        style: known ? `color: var(${s.better ? "--good" : "--critical"})` : "" },
        [el("span", { text: !known ? "—"
          : `${s.better ? "▼" : "▲"} ${num(Math.abs(s.change))}` })]),
    ]));
  }

  host.append(el("div", { class: "cmp-wrap" }, [
    el("h3", { class: "sub-h", text: "Start to now" }),
    el("div", { class: "sub", text:
      `First ${P.window} sessions (from ${P.from_date}) against the last ${P.window} `
      + `(to ${P.to_date}) — ${P.days} days. Lower is better in every row.` }),
    rows,
    el("div", { class: "note", text:
      "The level over the same stretch: " + (P.level_moved
        ? `${P.level_from} → ${P.level_to}.`
        : `${P.level_to} throughout — it needs three qualifying sessions to move, which `
          + "is right for a level and useless as weekly feedback. The closest unmet "
          + "threshold at the top of the page is the part that changes.") }),
  ]));
})();

/* focus — the slate, as a portfolio */
(() => {
  const host = document.getElementById("focus");
  const slate = MODEL.slate || [];
  if (!slate.length) { host.hidden = true; return; }

  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "Focus" }),
      el("div", { class: "sub", text:
        `${slate.length} of ${MODEL.categories.length} tracked patterns, chosen as a `
        + "portfolio rather than a top-five of one number: at least two from the clarity "
        + "tier, at most two from polish. A very frequent survivable error would otherwise "
        + "own every slot and crowd out what a listener actually loses." }),
    ]),
    el("a", { class: "action-link", href: "#patterns", text: "All patterns →" }),
  ]));

  const FLAGS = {
    stalled: ["!", "no better than three measured sessions ago"],
    thin: ["?", "ranked on fewer than five instances in total"],
    overdue: ["●", "past its review date"],
    frozen: ["❄", "no chance to make it lately — its absence streak is frozen"],
    "not-separable": ["~", "moved, but not beyond what chance would move it"],
  };

  const list = el("div", { class: "slate" });
  for (const target of slate) {
    const card = MODEL.categories.find((c) => c.category === target.category);
    const spark = el("div", { class: "slate-spark-line" });
    // A sibling, not a child of `spark`: responsive() clears spark's own
    // children every time it redraws (e.g. once its real width is known after
    // insertion), which would wipe anything appended inside it.
    const sparkCol = el("div", { class: "slate-spark" }, [spark]);
    if (card) {
      const own = Math.max(...card.series.map((pt) => pt.rate || 0), 0.5);
      responsive(spark, (w) => sparkline(w, card, own, 30), 60);
      // The line alone doesn't say whether its wiggle is good news: this is an
      // error rate, so down is always the direction to want, but nothing next
      // to the sparkline said so. DIRECTION already carries the colour used for
      // exactly this elsewhere on the page (Start to now, speech deltas) — it
      // just wasn't attached to a sparkline before.
      const dir = DIRECTION[card.direction];
      if (dir) sparkCol.append(el("div", { class: "spark-dir",
        style: `color: var(${dir.token})`, text: dir.text }));
    }
    list.append(el("div", { class: "slate-row" }, [
      el("div", { class: "slate-main" }, [
        el("a", { class: "slate-name", href: `#${target.slug}`, text: target.category }),
        el("div", { class: "slate-flags" }, [
          el("span", { class: `tier tier-${target.tier}`,
                       text: `${target.tier} · severity ${target.severity}` }),
          ...target.flags.map((f) => el("span", { class: "flag", title: (FLAGS[f] || ["", f])[1],
                                                  text: (FLAGS[f] || ["?", f])[0] + " " + f })),
        ]),
        el("div", { class: "slate-why", text: target.why || target.state_label }),
      ]),
      sparkCol,
      el("div", { class: "slate-do" }, [
        el("div", { class: "slate-action", text: target.action }),
        // Not a 0-10 score — it's the ranking weight that put this row here
        // (severity × how often it's happening), so a bare number invites
        // reading it as a grade. The order of the list already says "worse
        // first"; the title spells out what moved it there for anyone who asks.
        el("div", { class: "slate-impact", title: "Ranking weight: how severe this mistake is "
          + "combined with how often it's happening lately. Higher sorts first in this list — "
          + "it isn't a score out of 10.", text: `impact ${num(target.impact)}` }),
      ]),
    ]));
  }
  host.append(list);
})();


/* heatmap */
(() => {
  const host = document.getElementById("heatmap");
  const scroller = el("div", { class: "heat-scroll" }, [heatGrid(MODEL)]);
  // The grid is one column per session and overflows past about forty of them;
  // left at its default it opens on the oldest sessions on record, with the
  // ones anyone is looking for several screens off to the right. Scrolling it
  // is deliberately NOT done here: this section is built inside a hidden panel,
  // `[hidden]` is `display: none`, and a display:none subtree reports
  // scrollWidth 0 — so setting scrollLeft here wrote 0, which is the default it
  // was trying to change. `show()` does it on first reveal, when there is a
  // width to measure.
  const chart = el("div", {}, [scroller, el("div", { class: "heat-small", text:
    `${MODEL.categories.length} patterns across ${MODEL.dates.length} sessions. The grid is `
    + "one column per session and does not shrink to a phone \u2014 the same evidence, "
    + "ranked and with the diagnosis attached, is in Focus and in Every pattern." })]);
  const table = el("div", { hidden: "" }, [heatTable(MODEL)]);
  const toggle = el("button", { class: "ghost", type: "button", text: "Table view" });
  toggle.addEventListener("click", () => {
    const showTable = chart.hidden;
    chart.hidden = !showTable;
    table.hidden = showTable;
    toggle.textContent = showTable ? "Table view" : "Chart view";
  });
  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "Every tracked mistake, session by session" }),
      el("div", { class: "sub", text:
        "Ranked by impact. A hollow cell means the structure never came up that session, so "
        + "nothing was measured \\u2014 it is not a clean session." }),
    ]),
    toggle,
  ]));
  const legend = el("div", { class: "legend" });
  legend.append(el("div", { class: "legend-item" }, [
    el("span", { class: "key-box", style: "background: var(--heat-0)" }),
    el("span", { text: "clean (0)" }),
  ]));
  for (const bin of BINS) legend.append(el("div", { class: "legend-item" }, [
    el("span", { class: "key-box", style: `background: var(${bin.token})` }),
    el("span", { text: bin.label }),
  ]));
  legend.append(el("div", { class: "legend-item" }, [
    el("span", { class: "key-box",
                 style: "background: var(--heat-3); opacity: 0.45" }),
    el("span", { text: `≤ ${THIN_EVIDENCE} instances — too few to read` }),
  ]));
  legend.append(el("div", { class: "legend-item" }, [
    el("span", { class: "key-box", style: "box-shadow: inset 0 0 0 1px var(--hollow)" }),
    el("span", { text: "never came up" }),
  ]));
  chart.prepend(legend);          // the colour scale belongs to the grid, not the card
  host.append(chart);
  host.append(table);
})();



/* ---------- asking questions ---------- */
function barList(items, { max, label, value, tip }) {
  const top = max || Math.max(...items.map(value), 1);
  const wrap = el("div", { class: "bars" });
  for (const item of items) {
    const row = el("div", { class: "bar-row", tabindex: 0 }, [
      el("span", { class: "bar-label", text: label(item) }),
      el("div", { class: "bar-track" }, [
        el("i", { style: `width:${Math.max(2, (value(item) / top) * 100)}%` }),
      ]),
      el("span", { class: "bar-val", text: String(value(item)) }),
    ]);
    if (tip) {
      const rows = tip(item);
      const show = (ev) => showTip(ev.clientX ?? 0, ev.clientY ?? 0, label(item), rows);
      row.addEventListener("pointermove", show);
      row.addEventListener("focus", () => {
        const b = row.getBoundingClientRect(); showTip(b.right, b.top, label(item), rows);
      });
      row.addEventListener("pointerleave", hideTip);
      row.addEventListener("blur", hideTip);
    }
    wrap.append(row);
  }
  return wrap;
}

(() => {
  const host = document.getElementById("asking");
  const A = MODEL.asking;
  if (!A.totals.runs && !A.drill_totals.items && !A.practice.length) {
    host.hidden = true; return;
  }
  const share = (met, total) => total ? `${Math.round((met / total) * 100)}%` : "\\u2014";

  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "Asking questions" }),
      el("div", { class: "sub", text:
        "The half of this project a recording cannot measure. Whether a question was well "
        + "asked is not in a transcript \\u2014 it needs a situation, a reply that withholds "
        + "something, and criteria written in advance \\u2014 so nothing here has an "
        + "unmonitored-speech rung, and every score is small enough that it is shown next to "
        + "the number it divides." }),
    ]),
  ]));

  /* the headline numbers */
  const tiles = el("div", { class: "tiles", style: "margin-bottom:22px" }, [
    el("div", {}, [
      el("div", { class: "tile-label", text: "Scenario criteria met" }),
      el("div", { class: "tile-val", text: share(A.totals.met, A.totals.total) }),
      el("div", { class: "tile-note",
        text: `${A.totals.met} of ${A.totals.total} across ${A.totals.runs} runs` }),
    ]),
    el("div", {}, [
      el("div", { class: "tile-label", text: "By session" }),
      el("div", { class: "tile-val",
        text: A.by_date.map((d) => `${d.met}/${d.total}`).join(" \\u2192 ") || "\\u2014" }),
      el("div", { class: "tile-note",
        text: A.by_date.map((d) => d.date.slice(5)).join(" \\u2192 ") }),
    ]),
    el("div", {}, [
      el("div", { class: "tile-label", text: "Warm-up drill items tried" }),
      el("div", { class: "tile-val",
        text: `${A.drill_totals.attempted} of ${A.drill_totals.items}` }),
      el("div", { class: "tile-note", text: "too few to score" }),
    ]),
    el("div", {}, [
      el("div", { class: "tile-label", text: "Typed words in this mode" }),
      el("div", { class: "tile-val", text: int(A.practice_totals.words) }),
      el("div", { class: "tile-note",
        text: `${A.practice_totals.sessions} sessions, `
          + `${A.practice_totals.errors} tracked errors` }),
    ]),
  ]);
  host.append(tiles);

  /* which criteria fail, across scenarios */
  if (A.criteria.length) {
    host.append(el("h3", { text: "Which criteria fail",
      style: "font-size:13px;font-weight:600;margin:4px 0 4px" }));
    host.append(el("div", { class: "sub", style: "margin-bottom:10px", text:
      "The one dimension with repeats \\u2014 the same criterion failing across different "
      + "situations is a pattern rather than a property of one of them." }));
    host.append(barList(A.criteria, {
      label: (c) => c.criterion,
      value: (c) => c.count,
      tip: (c) => c.scenarios.map((name) => ({ value: "", name })),
    }));
  }

  /* every run */
  host.append(el("h3", { text: "Every scenario run",
    style: "font-size:13px;font-weight:600;margin:26px 0 10px" }));
  const runs = el("table");
  runs.append(el("thead", {}, [el("tr", {}, [
    el("th", { text: "Date" }), el("th", { class: "rung", text: "Scenario" }),
    el("th", { class: "rung", text: "Register" }), el("th", { class: "rung", text: "Function" }),
    el("th", { text: "Score" }), el("th", { class: "where", text: "Failed" }),
  ])]));
  const runBody = el("tbody");
  for (const r of A.runs) {
    runBody.append(el("tr", {}, [
      el("th", { scope: "row", text: r.date }),
      el("td", { class: "rung" }, [
        el("div", { text: r.scenario }),
        el("div", { class: "detail", text: r.pack }),
      ]),
      el("td", { class: "rung", text: r.register || "\\u2014" }),
      el("td", { class: "rung", text: r.function || "\\u2014" }),
      el("td" , {}, [el("div", { class: "cellrow" }, [
        el("span", { class: "dot",
          style: `background: var(${r.clean ? "--good" : r.met ? "--warning" : "--critical"})` }),
        el("span", { text: `${r.met}/${r.total}` }),
      ])]),
      el("td", { class: "where", text: r.failed.join(", ") || "nothing" }),
    ]));
  }
  runs.append(runBody);
  host.append(el("div", { class: "table-wrap" }, [runs]));

  const groupable = [...A.registers, ...A.functions].filter((g) => g.enough);
  if (!groupable.length) host.append(el("div", { class: "note", text:
    `${A.totals.runs} runs across ${A.registers.length} registers and ${A.functions.length} `
    + "functions \\u2014 close to one run each, so neither is aggregated into a score here. "
    + `${A.min_runs_to_group} runs in a group is the minimum for the number to mean anything; `
    + "until then the per-run table above is the whole of the evidence." }));

  /* the warm-up drills */
  if (A.drills.length) {
    host.append(el("h3", { text: "Warm-up drill blocks",
      style: "font-size:13px;font-weight:600;margin:26px 0 10px" }));
    const t = el("table");
    t.append(el("thead", {}, [el("tr", {}, [
      el("th", { text: "Drill" }), el("th", { class: "rung", text: "Pattern" }),
      el("th", { text: "Offered" }), el("th", { text: "Attempted" }),
      el("th", { text: "Correct" }), el("th", { text: "Last run" }),
    ])]));
    const body = el("tbody");
    for (const d of A.drills) {
      body.append(el("tr", {}, [
        el("th", { scope: "row", text: d.category }),
        el("td", { class: "rung", text: `${d.attempts} block(s)` }),
        el("td", { text: String(d.items) }),
        el("td" , {}, [el("div", { class: "cellrow", style: "justify-content:flex-end" }, [
          d.attempted ? null : el("span", { class: "dot",
            style: "box-shadow: inset 0 0 0 1px var(--hollow)" }),
          el("span", { text: String(d.attempted) }),
        ])]),
        el("td", { text: String(d.correct) }),
        el("td", { text: d.last_date }),
      ]));
    }
    t.append(body);
    host.append(el("div", { class: "table-wrap" }, [t]));
    host.append(el("div", { class: "note", text:
      `${A.drill_totals.attempted} of ${A.drill_totals.items} items offered have ever been `
      + "answered: one block ended early and the next was skipped by request. There is no "
      + "accuracy to report here \\u2014 the number in the Correct column is out of Attempted, "
      + "not out of Offered." }));
  }

  /* typed dialogue in this mode */
  if (A.practice.length) {
    host.append(el("h3", { text: "Typed dialogue",
      style: "font-size:13px;font-weight:600;margin:26px 0 10px" }));
    const t = el("table");
    t.append(el("thead", {}, [el("tr", {}, [
      el("th", { text: "Date" }), el("th", { class: "rung", text: "Focus" }),
      el("th", { text: "Words" }), el("th", { text: "Errors" }),
      el("th", { text: "Per 1,000" }), el("th", { text: "Re-productions" }),
    ])]));
    const body = el("tbody");
    for (const s of A.practice) {
      body.append(el("tr", {}, [
        el("th", { scope: "row", text: s.date }),
        el("td", { class: "rung" }, [
          el("div", { text: s.focus || "\\u2014" }),
          el("div", { class: "detail",
            text: s.breakdown.map((b) => `${b.category} \\u00d7${b.count}`).join(", ") }),
        ]),
        el("td", { text: int(s.words) }),
        el("td", { text: String(s.errors) }),
        el("td", { text: num(s.rate) }),
        el("td", { text: String(s.reproductions) }),
      ]));
    }
    t.append(body);
    host.append(el("div", { class: "table-wrap" }, [t]));
    host.append(el("div", { class: "note", text:
      "Words and errors are this mode's only, never pooled with conversation practice: an "
      + "asking session contributes words to the denominator while giving most grammar "
      + "categories no chance to appear. \\u201cRe-productions\\u201d counts the corrections "
      + "that landed; the column recording the ones asked for and missed was added after the "
      + "earliest sessions here, so those read as none rather than as unmeasured." }));
  }
})();

/* ---------- question patterns and untracked forms ---------- */
(() => {
  const host = document.getElementById("askpatterns");
  const A = MODEL.asking;
  if (!A.patterns.length && !A.provisional.length && !A.register_notes.length) {
    host.hidden = true; return;
  }

  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "Question patterns being tracked" }),
      el("div", { class: "sub", text:
        "asking_memory.md, by hand \\u2014 the counterpart of memory.md for a skill the "
        + "recording cannot see." }),
    ]),
  ]));

  if (A.patterns.length) {
    const t = el("table");
    t.append(el("thead", {}, [el("tr", {}, [
      el("th", { text: "Pattern" }), el("th", { class: "rung", text: "Status" }),
      el("th", { text: "Sessions with an error" }), el("th", { text: "Last error" }),
    ])]));
    const body = el("tbody");
    for (const p of A.patterns) {
      const active = p.status.toLowerCase().startsWith("active");
      body.append(el("tr", {}, [
        el("th", { scope: "row" }, [
          el("div", { class: "cellrow" }, [
            el("span", { text: p.name }),
            p.name === A.worst
              ? el("span", { class: "chip", text: "watch this one" }) : null,
          ]),
        ]),
        el("td", { class: "rung" }, [el("div", { class: "cellrow" }, [
          el("span", { class: "dot",
            style: `background: var(${active ? "--critical" : "--good"})` }),
          el("span", { text: p.status || "\\u2014" }),
        ])]),
        el("td", { text: p.sessions_with_error || "\\u2014" }),
        el("td", { text: p.last_error || "\\u2014" }),
      ]));
    }
    t.append(body);
    host.append(el("div", { class: "table-wrap" }, [t]));
  }

  if (A.provisional.length) {
    host.append(el("h3", { text: "Untracked forms",
      style: "font-size:13px;font-weight:600;margin:26px 0 8px" }));
    host.append(el("div", { class: "sub", style: "margin-bottom:10px", text:
      `Corrected in a session but covered by no category yet. Seen in `
      + `${A.promote_after} separate sessions it stops being a slip and earns a category `
      + "name and a drill of its own." }));
    const t = el("table");
    t.append(el("thead", {}, [el("tr", {}, [
      el("th", { text: "Form" }), el("th", { text: "Sessions" }), el("th", { text: "Times" }),
      el("th", { text: "Last seen" }), el("th", { class: "where", text: "" }),
    ])]));
    const body = el("tbody");
    for (const f of A.provisional) {
      body.append(el("tr", {}, [
        el("th", { scope: "row", text: f.name }),
        el("td", { text: String(f.sessions) }),
        el("td", { text: String(f.total) }),
        el("td", { text: f.last_seen }),
        el("td", { class: "where", text: f.ready ? "give it a category and a drill" : "" }),
      ]));
    }
    t.append(body);
    host.append(el("div", { class: "table-wrap" }, [t]));
  }

  if (A.register_notes.length) {
    const notes = el("details", {}, [
      el("summary", { text: `Register notes (${A.register_notes.length})` }),
    ]);
    for (const note of A.register_notes)
      notes.append(el("div", { class: "note", style: "margin-top:8px", text: note }));
    host.append(notes);
  }
})();

/* ---------- one small chart, own scale, gaps for what wasn't measured ---------- */
function smallLine(width, points, decimals) {
  const H = 58, pad = 4, left = 0;
  const values = points.map((p) => p.value).filter((v) => v !== null && v !== undefined);
  const top = Math.max(...values, 0) * 1.15 || 1;
  const x = (i) => left + pad + (points.length < 2 ? 0
    : (i / (points.length - 1)) * (width - left - pad * 2));
  const y = (v) => H - pad - (v / top) * (H - pad * 2);
  const root = svg("svg", { viewBox: `0 0 ${width} ${H}`, width, height: H });
  root.append(svg("line", { x1: left, x2: width, y1: H - pad, y2: H - pad,
                            stroke: css("--grid"), "stroke-width": 1 }));
  const color = css("--series-1");
  let run = [];
  const flush = () => {
    if (run.length > 1)
      root.append(svg("path", { d: "M" + run.map((p) => `${p[0]},${p[1]}`).join("L"),
                                fill: "none", stroke: color, "stroke-width": 2,
                                "stroke-linejoin": "round", "stroke-linecap": "round" }));
    else if (run.length === 1)
      root.append(svg("circle", { cx: run[0][0], cy: run[0][1], r: 2.5, fill: color }));
    run = [];
  };
  points.forEach((p, i) => {
    if (p.value === null || p.value === undefined) flush(); else run.push([x(i), y(p.value)]);
  });
  flush();
  const lastIndex = points.reduce(
    (best, p, i) => (p.value === null || p.value === undefined ? best : i), -1);
  if (lastIndex >= 0)
    root.append(svg("circle", { cx: x(lastIndex), cy: y(points[lastIndex].value), r: 4,
                                fill: color, stroke: css("--surface"), "stroke-width": 2 }));

  points.forEach((p, i) => {                       // a hit band per session, focusable
    const half = points.length < 2 ? width : (width - left - pad * 2) / (points.length - 1) / 2;
    const band = svg("rect", { x: Math.max(0, x(i) - half), y: 0,
                               width: Math.max(1, half * 2), height: H,
                               fill: "transparent", tabindex: 0 });
    const rows = [{
      value: p.value === null || p.value === undefined ? "not measured" : num(p.value, decimals),
      name: "",
    }];
    const show = (ev) => showTip(ev.clientX ?? 0, ev.clientY ?? 0, p.date, rows);
    band.addEventListener("pointermove", show);
    band.addEventListener("focus", () => {
      const b = band.getBoundingClientRect(); showTip(b.right, b.top, p.date, rows);
    });
    band.addEventListener("pointerleave", hideTip);
    band.addEventListener("blur", hideTip);
    root.append(band);
  });
  return root;
}

/* ---------- words to retire ---------- */
(() => {
  const host = document.getElementById("vocabulary");
  const V = MODEL.vocabulary;
  if (!V.rows || !V.rows.length) { host.hidden = true; return; }

  const MOVE = {
    rising: { token: "--critical", text: "still rising" },
    level: { token: "--warning", text: "not budging" },
    falling: { token: "--good", text: "falling" },
    // Said too rarely to have a direction — the same restraint the mistake
    // trends apply, for the same reason.
    "too few to tell": { token: "--muted", text: "too few to tell" },
    "never said": { token: "--muted", text: "never said" },
  };

  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "Words to retire" }),
      el("div", { class: "sub", text:
        "memory.md carries a table of phrases to stop using and what to say instead. It is "
        + "written every session and read every session, and nothing ever checked it \\u2014 "
        + "a standing instruction with no feedback loop, which is the kind of advice that "
        + "can be wrong for months without anyone noticing. Counted here over the reliable "
        + "lines of every archived session, worst first." }),
    ]),
  ]));

  const bars = (counts) => {
    const top = Math.max(...counts, 1);
    const wrap = el("div", { class: "spark-cells" });
    counts.forEach((n) => {
      const bar = el("i", { style: `height:${n ? Math.max(12, (n / top) * 100) : 6}%` });
      if (!n) bar.dataset.zero = "1";
      wrap.append(bar);
    });
    return wrap;
  };

  for (const row of V.rows) {
    const move = MOVE[row.movement] || MOVE.level;
    const detail = row.replacements.length
      ? "instead: " + row.replacements
          .map((r) => `${r.phrase} (${r.total}×, ${r.movement})`).join(", ")
      : "no replacement from the table has been said yet";
    const block = el("div", { class: "vrow" }, [
      el("div", {}, [
        el("div", { class: "vphrase", text: row.phrase }),
        el("div", { class: "vsub", text: detail }),
      ]),
      bars(row.counts),
      el("div", {}, [
        el("div", { class: "vmove", style: `color: var(${move.token})` }, [
          el("span", { class: "dot", style: `background: var(${move.token})` }),
          el("span", { text: move.text }),
        ]),
        el("div", { class: "vsub", style: "text-align:right",
                    text: `${row.total}× in all` }),
      ]),
    ]);
    const rows = [
      { value: String(row.total), name: "times in all" },
      { value: `${num(row.early, 2)} → ${num(row.late, 2)}`,
        name: "per 1,000 words, first half to second" },
    ];
    const show = (ev) => showTip(ev.clientX ?? 0, ev.clientY ?? 0, row.phrase, rows);
    block.addEventListener("pointermove", show);
    block.addEventListener("pointerleave", hideTip);
    host.append(block);
  }

  const notes = [];
  if (V.never_said.length) notes.push(
    `${V.never_said.length} entries in the table have never appeared in an archived `
    + `session: ${V.never_said.slice(0, 4).join(", ")}`
    + (V.never_said.length > 4 ? ", …" : "") + ".");
  notes.push("A count cannot tell a word used well from one leaned on \\u2014 a phrase can "
    + "be on the list for being vague rather than forbidden. Read it as a prompt to look. "
    + "Counts are on word boundaries over reliable lines only, so “cool” does not "
    + "collect “cooling”.");
  host.append(el("div", { class: "note", text: notes.join(" ") }));
})();

/* ---------- how it was spoken ---------- */
(() => {
  const host = document.getElementById("speech");
  const S = MODEL.speech;
  if (!S.sessions.length) { host.hidden = true; return; }

  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "How it was spoken" }),
      el("div", { class: "sub", text:
        "Pace, hesitation and pauses \\u2014 measured over the reliable lines only, the same "
        + "population the grammar analysis uses." }),
    ]),
  ]));

  /* pace: one series per measurement basis, never joined across them */
  const paceSeries = S.pace.series.map((s, i) => ({
    key: s.key, label: `${s.label} \\u00b7 ${s.measured} session${s.measured === 1 ? "" : "s"}`,
    token: i === 0 ? "--series-1" : "--series-2",
  }));
  host.append(el("h3", { text: "Speaking pace",
    style: "font-size:13px;font-weight:600;margin:6px 0 8px" }));
  host.append(el("div", { class: "legend" }, paceSeries.map((s) =>
    el("div", { class: "legend-item" }, [
      el("span", { class: "key-line", style: `background: var(${s.token})` }),
      el("span", { text: s.label }),
    ]))));
  const pacePlot = el("div", { class: "plot" });
  host.append(pacePlot);
  responsive(pacePlot, (w) => lineChart(w, S.pace.rows, paceSeries, {
    decimals: 1,
    extraRows: (d) => [
      { value: num(d.speech_minutes, 1), name: "minutes of speech" },
      { value: int(d.reliable_words), name: "reliable words" },
    ],
  }));
  host.append(el("div", { class: "note", text:
    "Two lines because words per minute is measured against two different denominators, and "
    + "they are not comparable. Diarization hands over VAD-tight turns; without it whisper's "
    + "own segments swallow the pauses inside them \\u2014 the same speaker at the same speed "
    + "reads far faster one way than the other. The two recording modes alternate through "
    + "this history, so the honest chart is two series with gaps rather than one line with a "
    + `step in it. ${S.pace.unmeasured} backfilled session(s) are absent: they were counted `
    + "from an archived transcript, with no clock to measure time against." }));

  /* the small multiples */
  host.append(el("h3", { text: "Hesitation and pauses",
    style: "font-size:13px;font-weight:600;margin:26px 0 10px" }));
  const grid = el("div", { class: "metrics" });
  for (const metric of S.metrics) {
    const measured = metric.points.filter((p) => p.value !== null && p.value !== undefined);
    const latest = measured.length ? measured[measured.length - 1] : null;
    const first = measured.length ? measured[0] : null;
    const panel = el("div", { class: "metric" });
    panel.append(el("div", { class: "mlabel", text: metric.label }));
    panel.append(el("div", { class: "val" }, [
      el("span", { text: latest ? num(latest.value, metric.decimals) : "\\u2014" }),
      el("span", { class: "unit", text: ` ${metric.unit}` }),
    ]));
    if (latest && first && measured.length > 1 && first.value !== latest.value) {
      const down = latest.value < first.value;
      // Down is better for all four: fewer fillers, fewer crutch markers,
      // shorter and fewer pauses. Stated rather than assumed from the arrow.
      panel.append(el("div", { class: "delta-s",
        style: `color: var(${down ? "--good" : "--critical"})` }, [
        el("span", { text: down ? "\\u25bc" : "\\u25b2" }),
        el("span", { text: `${num(Math.abs(latest.value - first.value), metric.decimals)} `
          + `since ${first.date}` }),
      ]));
    }
    const plot = el("div", { class: "plot", style: "margin-top:8px" });
    panel.append(plot);
    responsive(plot, (w) => smallLine(w, metric.points, metric.decimals));
    panel.append(el("div", { class: "mnote", text: metric.solo_only
      ? `${metric.note} Solo recordings only.` : metric.note }));
    grid.append(panel);
  }
  host.append(grid);
  if (S.metrics.some((m) => m.solo_only)) host.append(el("div", { class: "note", text:
    "The two pause measures are blank for the diarized sessions by design, not by accident: "
    + "in a recording with another voice in it the gap between two of your lines is mostly "
    + "the other person talking, so the same number would mean two different things." }));
})();

/* ---------- how reliable each session was ---------- */
(() => {
  const host = document.getElementById("quality");
  const S = MODEL.speech;
  if (!S.sessions.length) { host.hidden = true; return; }
  const pct = (v) => v === null || v === undefined ? "\\u2014" : `${Math.round(v * 100)}%`;

  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "How reliable each session was" }),
      el("div", { class: "sub", text:
        "Input quality, not speaking quality: high values mean the microphone, not the "
        + "speaker. It belongs here rather than in the charts above because when it moves, "
        + "every number on this page changes meaning \\u2014 a session that lost a quarter of "
        + "its words is a weaker measurement of all of them." }),
    ]),
  ]));

  host.append(el("div", { class: "notice", text: S.any_unreliable
    ? `At least one session is at or above the ${pct(S.warn_share)} word-share mark where `
      + "the pipeline stops treating it as comparable. Check the mic before reading anything "
      + "into that session's fluency."
    : `No session on record reaches the ${pct(S.warn_share)} word-share mark where the `
      + "pipeline warns that a session is not comparable. Read by line the numbers look far "
      + "worse, but that mostly counts two-word replies, which is why the word share is the "
      + "one to act on." }));

  const table = el("table");
  table.append(el("thead", {}, [el("tr", {}, [
    el("th", { text: "Session" }), el("th", { class: "rung", text: "Mode" }),
    el("th", { text: "Files" }), el("th", { text: "Lines" }),
    el("th", { text: "Low-conf. lines" }), el("th", { class: "rung", text: "Words lost" }),
    el("th", { text: "Reliable words" }), el("th", { text: "Speech" }),
  ])]));
  const body = el("tbody");
  // Newest first. The reason this table exists is "is the session I just
  // recorded any good", and that row was at the bottom of a list that grows
  // forever.
  const recent = S.sessions.slice().reverse().slice(0, TABLE_ROWS);
  for (const q of recent) {
    const share = q.word_share;
    const meter = el("div", { class: "meter" }, [
      el("i", { style: `width:${Math.min(100, (share || 0) * 100)}%;`
        + `background: var(${q.unreliable ? "--critical" : "--series-1"})` }),
      el("u", { style: `left:${S.warn_share * 100}%`, title: "the warning threshold" }),
    ]);
    body.append(el("tr", {}, [
      el("th", { scope: "row", text: q.date }),
      el("td", { class: "rung", text: q.mode || "\\u2014" }),
      el("td", { text: q.files === null ? "\\u2014" : String(q.files) }),
      el("td", { text: int(q.total_lines) }),
      el("td", { text: `${int(q.low_confidence_lines)} \\u00b7 ${pct(q.line_share)}` }),
      el("td", { class: "rung" }, [
        el("div", { class: "cellrow" }, [
          el("span", { text: pct(share) }), meter,
        ]),
      ]),
      el("td", { text: int(q.reliable_words) }),
      el("td", { text: q.speech_minutes ? `${num(q.speech_minutes, 1)} min` : "\\u2014" }),
    ]));
  }
  table.append(body);
  table.append(el("caption", { text:
    "\\u201cWords lost\\u201d is the share of words whisper was unsure of \\u2014 the reading "
    + "the pipeline acts on. The tick marks the threshold at which it warns." }));
  host.append(el("div", { class: "table-wrap" }, [table]));
  moreRows(host, S.sessions.length, recent.length, "recorded sessions");
})();

/* ---------- what to work on: one expandable row per pattern ---------- */
(() => {
  const host = document.getElementById("patterns");
  const L = MODEL.ladder;
  if (!L.rows.length) { host.hidden = true; return; }
  const byCategory = new Map(MODEL.categories.map((c) => [c.category, c]));

  const ACTIONS = {
    "retiring": "Move it to Improvements in memory.md",
    "no-drill": "Write a drill",
    "thin-evidence": "Drill it again — one item is not a score",
    "form-unreliable": "Keep drilling until the form is reliable",
    "automaticity-gap": "More drilling will not fix this — produce it in dialogue",
    "clean": "Watch it — one clean session is not a streak",
  };

  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "What to work on" }),
      el("div", { class: "sub", text:
        "Ranked by impact — severity × √(recency-weighted rate), the ranking "
        + "python -m voxlib.mistakes prints, so the page and the CLI always agree. Three "
        + "files measure three different things about the same mistake, and the rung a row "
        + "fails on says what to do about it: a form drilled to 100% that still appears in "
        + "every recording is not a knowledge problem. Open a row for its trend, its worked "
        + "examples and its notes." }),
    ]),
  ]));

  host.append(el("div", { class: "rungs" }, [
    el("div", { class: "rung-def" }, [
      el("b", { text: "1 · Knows the form" }),
      el("span", { text: "drills.csv — the only score here with a real denominator. "
        + "Blocked means the pattern was named; mixed means it had to be noticed." }),
    ]),
    el("div", { class: "rung-def" }, [
      el("b", { text: "2 · Produces it when attending" }),
      el("span", { text: "practice_history.csv — typed dialogue, errors per 1,000 words "
        + "the owner produced." }),
    ]),
    el("div", { class: "rung-def" }, [
      el("b", { text: "3 · Produces it unmonitored" }),
      el("span", { text: "mistakes.csv — the recording, per 1,000 reliable words. The "
        + "only rung that measures speech." }),
    ]),
  ]));

  if (!L.attended_sessions) host.append(el("div", { class: "notice", text:
    `Rung 2 has no measurements. All ${L.asking_sessions} recorded practice sessions were `
    + "question practice (mode “ask”); conversation practice — the mode that "
    + "drills these grammar categories in dialogue — has never been recorded, so nothing "
    + "bridges the drill and the recording. Grammar errors logged during question practice "
    + "are shown as a count, not a rate: those sessions add words to the denominator without "
    + "giving most of these categories a chance to appear." }));

  if (L.states["no-drill"]) host.append(el("div", { class: "notice", text:
    `${L.states["no-drill"]} of the ${L.rows.length} tracked mistakes have no drill, so `
    + "rungs 1 and 2 cannot be measured for them at all — the only evidence on record "
    + "is what the recording caught. A drill is the cheapest way to find out whether one of "
    + "them is a knowledge gap or an automaticity gap; drills/README.txt has the format." }));

  /* ---- controls: the state filter and the sort, in one row ---- */
  const order = Object.keys(L.state_labels).filter((k) => L.states[k]);
  let active = null;
  const bar = el("div", { class: "chipbar" });
  const sort = el("select", { id: "sort-by" }, [
    el("option", { value: "impact", text: "impact" }),
    el("option", { value: "latest", text: "latest rate" }),
    el("option", { value: "severity", text: "severity" }),
    el("option", { value: "recent", text: "most recently seen" }),
    el("option", { value: "due", text: "next due" }),
    el("option", { value: "name", text: "name" }),
  ]);
  const hide = el("input", { type: "checkbox", id: "hide-clean" });
  const table = el("div");

  const dot = (token) => el("span", { class: "dot", style: `background: var(${token})` });
  const hollow = () => el("span", { class: "dot",
    style: "box-shadow: inset 0 0 0 1px var(--hollow)" });

  const cell = (status, main, detail) => {
    const td = el("td", { class: "rung" });
    td.append(el("div", { class: "cellrow" }, [
      status === null ? hollow() : dot(status), el("span", { text: main }),
    ]));
    if (detail) td.append(el("div", { class: "detail", text: detail }));
    return td;
  };

  const rungOne = (r) => {
    const d = r.drill;
    if (!d || !d.attempted) return cell(null, "never drilled");
    const pct = `${Math.round(d.accuracy * 100)}% (${d.correct}/${d.attempted})`;
    const detail = `blocked ${d.blocked.correct}/${d.blocked.attempted}`
      + ` · mixed ${d.mixed.correct}/${d.mixed.attempted}`;
    if (d.attempted < 5) return cell("--warning", pct, `${detail} — too few to tell`);
    return cell(d.accuracy >= 0.8 ? "--good" : "--critical", pct, detail);
  };

  const rungTwo = (r) => {
    if (r.attended_rate !== null && r.attended_rate !== undefined)
      return cell(r.attended_rate > 0 ? "--critical" : "--good", num(r.attended_rate),
                  "per 1,000 typed words");
    if (r.attended_in_asking)
      return cell("--warning", `${r.attended_in_asking}×`, "question practice only");
    return cell(null, "not measured");
  };

  const rungThree = (r) => {
    if (r.speech_rate === null || r.speech_rate === undefined)
      return cell(null, "not measured", `untested ×${r.untested_since}`);
    const detail = r.absence_streak
      ? `clean ×${r.absence_streak} running`
      : `${DIRECTION[r.direction] ? DIRECTION[r.direction].text : r.direction}`
        + `${r.stalled ? " · stalled" : ""}`;
    // The count beside the rate: a rate on its own hides whether it rests on
    // one instance or twenty.
    const shown = num(r.speech_rate)
      + (r.speech_count ? ` (${r.speech_count})` : "");
    return cell(r.speech_rate > 0 ? "--critical" : "--good", shown, detail);
  };

  /* ---- the rows ---- */
  // Which patterns are open. Survives a re-render on purpose — unlike anything
  // about the DOM, which `build` recreates from scratch every time.
  const expanded = new Set();

  const row = (r) => {
    const cat = byCategory.get(r.category);
    const detailId = `${r.slug}-detail`;
    const open = expanded.has(r.slug);

    const toggle = el("button", { class: "row-toggle", type: "button" });
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-controls", detailId);
    toggle.append(el("span", { class: "caret", text: open ? "▼" : "▶" }));
    const name = el("div", {}, [
      el("div", { class: "pname" }, [
        el("span", { class: "sev", text: `s${r.severity} ` }),
        el("span", { text: r.category }),
      ]),
    ]);
    // The most recent worked example stays visible without opening anything —
    // it is the one line on this page you can practise from.
    const latest = cat && cat.note && cat.note.examples.length
      ? cat.note.examples[cat.note.examples.length - 1] : null;
    if (latest) {
      const line = el("div", { class: "row-ex",
        title: `${latest.wrong} → ${latest.right}` });
      line.append(el("span", { class: "wrong", text: latest.wrong }));
      line.append(el("span", { text: " → " }));
      const right = el("span", { class: "right" });
      right.append(inlineMarkdown(latest.right));
      line.append(right);
      name.append(line);
    }
    toggle.append(name);

    const due = r.next_due
      ? el("span", { class: r.overdue ? "overdue" : null,
                     text: r.overdue ? `${r.next_due} · overdue` : r.next_due })
      : el("span", { class: "detail", text: "not scheduled" });

    const tr = el("tr", { id: r.slug }, [
      el("th", { scope: "row" }, [toggle]),
      rungOne(r), rungTwo(r), rungThree(r),
      el("td", {}, [due]),
      el("td", { class: "where" }, [
        el("div", { text: L.state_labels[r.state] }),
        el("div", { class: "detail action", text: ACTIONS[r.state] || "" }),
      ]),
    ]);

    const detailTr = el("tr", { class: "detail-row" });
    if (!open) detailTr.hidden = true;
    const holder = el("td", { id: detailId, colSpan: 6 });
    detailTr.append(holder);
    // Built on first open: a detail per pattern, notes and charts included, is a
    // lot of DOM to create for rows nobody looks at.
    //
    // The guard asks this cell whether it is already filled, rather than
    // remembering which patterns have been built. A set of slugs outlives the
    // nodes it was describing: `build` replaces every row, so after a re-render
    // — a sort, a filter chip, or following another pattern's link — the slug
    // was still marked built while the new cell was empty, and the row opened
    // to nothing.
    const fill = () => {
      if (holder.firstChild || !cat) return;
      holder.append(patternDetail(cat));
    };
    if (open) fill();

    toggle.addEventListener("click", () => {
      const nowOpen = !expanded.has(r.slug);
      if (nowOpen) { expanded.add(r.slug); fill(); } else { expanded.delete(r.slug); }
      detailTr.hidden = !nowOpen;
      toggle.setAttribute("aria-expanded", String(nowOpen));
      toggle.firstChild.textContent = nowOpen ? "▼" : "▶";
      if (nowOpen) window.dispatchEvent(new Event("resize"));
    });

    return [tr, detailTr];
  };

  const build = () => {
    let rows = active ? L.rows.filter((r) => r.state === active) : L.rows;
    if (hide.checked) rows = rows.filter((r) => r.state !== "retiring");
    const rank = {
      impact: (a, b) => b.impact - a.impact,
      latest: (a, b) => (b.speech_rate ?? -1) - (a.speech_rate ?? -1),
      severity: (a, b) => b.severity - a.severity || b.impact - a.impact,
      recent: (a, b) => (b.last_seen || "").localeCompare(a.last_seen || ""),
      due: (a, b) => (a.next_due || "9999").localeCompare(b.next_due || "9999"),
      name: (a, b) => a.category.localeCompare(b.category),
    };
    rows = [...rows].sort(rank[sort.value]);

    table.textContent = "";
    const t = el("table");
    t.append(el("thead", {}, [el("tr", {}, [
      el("th", { text: `Mistake (${rows.length})` }),
      el("th", { class: "rung", text: "1 · Knows the form" }),
      el("th", { class: "rung", text: "2 · Attending" }),
      el("th", { class: "rung", text: "3 · Unmonitored" }),
      el("th", { text: "Next due" }),
      el("th", { class: "where", text: "Where it breaks" }),
    ])]));
    const body = el("tbody");
    for (const r of rows) for (const node of row(r)) body.append(node);
    t.append(body);
    table.append(el("div", { class: "table-wrap" }, [t]));
  };

  const chips = [];
  const paint = () => chips.forEach(([b, k]) =>
    b.setAttribute("aria-pressed", String(active === k)));
  for (const key of [null, ...order]) {
    const b = el("button", { class: "state", type: "button" }, [
      el("span", { class: "count", text: String(key ? L.states[key] : L.rows.length) }),
      el("span", { text: key ? L.state_labels[key] : "all patterns" }),
    ]);
    b.addEventListener("click", () => {
      active = active === key ? null : key;
      paint(); build();
    });
    chips.push([b, key]);
    bar.append(b);
  }
  paint();
  host.append(bar);
  host.append(el("div", { class: "controls" }, [
    el("label", { htmlFor: "sort-by", text: "Sort by" }), sort,
    el("label", { htmlFor: "hide-clean" },
       [hide, el("span", { text: " Hide the ones ready to retire" })]),
  ]));
  host.append(table);

  sort.addEventListener("change", build);
  hide.addEventListener("change", build);

  // A pattern can be linked to: #pattern-<name> opens that row. The page had
  // one of these per tracked pattern and no way to point at any of them.
  const openFromHash = () => {
    const slug = location.hash.slice(1);
    if (!slug || !L.rows.some((r) => r.slug === slug)) return false;
    if (!expanded.has(slug) || !document.getElementById(slug)) {
      expanded.add(slug);
      active = null;                 // a filter may be hiding the row
      paint();
      build();
    }
    const target = document.getElementById(slug);
    if (target) target.scrollIntoView({ block: "center" });
    return true;
  };

  build();
  if (!openFromHash()) {
    // Otherwise open the top-ranked row, so the page always shows one pattern's
    // examples and notes without a click.
    expanded.add(L.rows[0].slug);
    build();
  }
  window.addEventListener("hashchange", openFromHash);

  if (L.dialogue_only.length) {
    const list = el("div", { class: "note" });
    list.append(el("div", { text:
      "On the practice schedule but absent from the table above, because the recording "
      + "cannot measure them — question-asking is not a grammar category, so these have "
      + "no rung 3:" }));
    for (const d of L.dialogue_only) {
      list.append(el("div", { style: "margin-top:6px" }, [
        el("span", { text: `${d.category} — last drilled ${d.last_drilled}, streak `
          + `${d.streak}, due ` }),
        el("span", { class: d.overdue ? "overdue" : null,
                     text: d.overdue ? `${d.next_due} (overdue)` : d.next_due }),
      ]));
    }
    host.append(list);
  }
})();

/* ---------- what is working ---------- */
(() => {
  const host = document.getElementById("working");
  if (!MODEL.working.length) { host.hidden = true; return; }

  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "What's working" }),
      el("div", { class: "sub", text:
        "The counterpart of the list above, and nothing on it is rounded in a flattering "
        + "direction: every line is a measurement that moved the right way, and the block "
        + "does not appear at all when none did." }),
    ]),
  ]));

  const list = el("div", { class: "actions" });
  for (const win of MODEL.working) {
    list.append(el("div", { class: "action-row" }, [
      el("div", { class: "action-n" }, [
        el("span", { class: "dot", style: "background: var(--good)" }),
      ]),
      el("div", {}, [
        el("div", { class: "action-title", text: win.title }),
        el("div", { class: "action-detail", text: win.detail }),
        el("a", { class: "action-link", href: `#${win.anchor}`,
                  text: `↓ ${SECTION_LABELS[win.anchor] || win.anchor}` }),
      ]),
    ]));
  }
  host.append(list);
})();

/* ---------- the level line ---------- */
function levelChart(width, L) {
  const top = L.scale.length - 1;
  const bottom = L.below_scale;                 // one row for "below B1"
  const rows = top - bottom + 1;
  const rowH = 26;
  const M = { top: 10, right: 46, bottom: 30, left: 116 };
  const H = M.top + rows * rowH + M.bottom;
  const iw = width - M.left - M.right;
  const readings = L.readings;
  const x = (i) => M.left + (readings.length < 2 ? iw / 2
    : (i / (readings.length - 1)) * iw);
  const y = (rung) => M.top + (top - rung) * rowH + rowH / 2;

  const root = svg("svg", { viewBox: `0 0 ${width} ${H}`, width, height: H, role: "img" });

  for (let rung = bottom; rung <= top; rung += 1) {
    root.append(svg("line", { x1: M.left, x2: M.left + iw, y1: y(rung), y2: y(rung),
                              stroke: css("--grid"), "stroke-width": 1 }));
    root.append(Object.assign(
      svg("text", { x: M.left - 10, y: y(rung) + 4, fill: css("--muted"), "font-size": 11,
                    "text-anchor": "end" }),
      { textContent: rung < 0 ? "below B1" : L.scale[rung] }));
  }
  const every = readings.length > 8 ? 2 : 1;
  readings.forEach((r, i) => {
    if (i % every && i !== readings.length - 1) return;
    root.append(Object.assign(
      svg("text", { x: x(i), y: H - 10, fill: css("--muted"), "font-size": 11,
                    "text-anchor": "middle" }),
      { textContent: shortDate(r.date) }));
  });

  // The level itself: a step, because it only changes on the session that
  // completes a qualifying run — between those it is flat by definition.
  const levelled = readings.map((r, i) => [i, r.level]).filter(([, v]) => v !== null);
  if (levelled.length) {
    let d = "";
    levelled.forEach(([i, value], n) => {
      if (!n) { d += `M${x(i)},${y(value)}`; return; }
      d += `L${x(i)},${y(levelled[n - 1][1])}L${x(i)},${y(value)}`;
    });
    root.append(svg("path", { d, fill: "none", stroke: css("--series-1"),
                              "stroke-width": 2, "stroke-linejoin": "round",
                              "stroke-linecap": "round" }));
    const [lastIndex, lastValue] = levelled[levelled.length - 1];
    root.append(svg("circle", { cx: x(lastIndex), cy: y(lastValue), r: 4.5,
                                fill: css("--series-1"), stroke: css("--surface"),
                                "stroke-width": 2 }));
  }

  // Every session's own reading, which is what the level is smoothed out of.
  readings.forEach((r, i) => {
    if (r.rung === null) return;
    root.append(svg("circle", { cx: x(i), cy: y(r.rung), r: r.reliable ? 3.5 : 2.5,
                                fill: r.reliable ? css("--series-2") : "none",
                                stroke: r.reliable ? css("--surface") : css("--series-2"),
                                "stroke-width": r.reliable ? 1.5 : 1 }));
  });

  const hair = svg("line", { y1: M.top, y2: M.top + rows * rowH, stroke: css("--axis"),
                             "stroke-width": 1, opacity: 0 });
  root.append(hair);
  readings.forEach((r, i) => {
    const half = readings.length < 2 ? iw : iw / (readings.length - 1) / 2;
    const band = svg("rect", { x: Math.max(M.left, x(i) - half), y: M.top,
                               width: Math.max(1, half * 2), height: rows * rowH,
                               fill: "transparent", tabindex: 0 });
    const rows_ = [
      { color: css("--series-1"), value: r.level_label, name: "level" },
      { color: css("--series-2"), value: r.rung_label, name: "this session alone" },
    ];
    if (r.blockers.length) rows_.push({ value: r.blockers.join(", "), name: "held back by" });
    if (!r.reliable) rows_.push({ value: "not comparable", name: "too many words lost" });
    const show = (ev) => {
      hair.setAttribute("x1", x(i)); hair.setAttribute("x2", x(i));
      hair.setAttribute("opacity", 1);
      showTip(ev.clientX ?? 0, ev.clientY ?? 0, r.date, rows_);
    };
    band.addEventListener("pointermove", show);
    band.addEventListener("focus", () => {
      const b = band.getBoundingClientRect();
      hair.setAttribute("x1", x(i)); hair.setAttribute("x2", x(i));
      hair.setAttribute("opacity", 1);
      showTip(b.right, b.top, r.date, rows_);
    });
    band.addEventListener("pointerleave", () => { hair.setAttribute("opacity", 0); hideTip(); });
    band.addEventListener("blur", () => { hair.setAttribute("opacity", 0); hideTip(); });
    root.append(band);
  });
  return root;
}

(() => {
  const host = document.getElementById("level");
  const L = MODEL.level;
  if (!L.readings || !L.readings.length) { host.hidden = true; return; }
  const cur = L.current;

  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "Level" }),
      el("div", { class: "sub", text:
        "A CEFR band is about a year wide, which makes it useless as weekly feedback \\u2014 "
        + "scores_history.csv has recorded the same letter for every session so far. This "
        + "cuts the band into rungs and earns each one against explicit thresholds, so the "
        + "same history always gives the same answer. It is calibrated against your own "
        + "record: a rung on your line, not an exam result." }),
    ]),
  ]));

  host.append(el("div", { class: "lvl-head" }, [
    el("div", {}, [
      el("div", { class: "lvl-val", text: cur.label }),
      el("div", { class: "lvl-note", text: cur.index === null ? "not yet established"
        : `rung ${cur.index + 1} of ${L.scale.length}`
          + (L.target ? ` \\u00b7 next is ${L.target.label}` : "")
          + (cur.session_label !== cur.label
             ? ` \\u00b7 this session alone reads ${cur.session_label}` : "") }),
    ]),
    el("div", { style: "flex:1 1 300px" }, [
      el("div", { class: "lvl-note", style: "margin-top:0", text: cur.blockers.length
        ? "Held here by " + L.dimensions.filter((d) => d.blocking)
            .map((d) => d.label.toLowerCase()).join(" and ")
          + `. The rung moves when all but one dimension reach it, none is more than one `
          + `rung below, and that holds for ${L.promotion_sessions} sessions running.`
        : `The rung moves when all but one dimension reach it and that holds for `
          + `${L.promotion_sessions} sessions running.` }),
      L.floor ? el("div", { class: "lvl-note", text:
        `The line has not moved, but the floor under it has: the worst single session was `
        + `${L.floor.worst_label}, last seen on ${L.floor.last_at_worst}, and none of the `
        + `${L.floor.sessions_since} sessions since has read below `
        + `${L.floor.floor_since_label}.` }) : null,
    ]),
  ]));

  const plot = el("div", { class: "plot", style: "margin-top:18px" });
  host.append(el("div", { class: "legend", style: "margin-top:20px" }, [
    el("div", { class: "legend-item" }, [
      el("span", { class: "key-line", style: "background: var(--series-1)" }),
      el("span", { text: "level \\u2014 what the evidence sustains" }),
    ]),
    el("div", { class: "legend-item" }, [
      el("span", { class: "key-box",
                   style: "background: var(--series-2); border-radius: 50%" }),
      el("span", { text: "one session on its own" }),
    ]),
  ]));
  host.append(plot);
  responsive(plot, (w) => levelChart(w, L));

  /* the four dimensions, and what the next rung asks of each */
  const grid = el("div", { class: "dims" });
  for (const dim of L.dimensions) {
    const block = el("div", {});
    block.append(el("div", { class: "dim-name" }, [
      el("span", { text: dim.label }),
      el("span", { class: "dim-rung" }, [
        dim.rung === null
          ? el("span", { class: "dot", style: "box-shadow: inset 0 0 0 1px var(--hollow)" })
          : el("span", { class: "dot",
              style: `background: var(${dim.blocking ? "--warning" : "--good"})` }),
        el("span", { text: dim.rung_label }),
      ]),
    ]));
    for (const m of dim.measures) {
      const row = el("div", { class: "mrow" });
      row.append(el("div", { class: "mlab" }, [
        el("span", { text: m.label }),
        el("span", { class: "mval",
                     text: m.value === null ? "not measured" : trim(m.value) }),
      ]));
      if (m.threshold !== null && m.threshold !== undefined) {
        row.append(el("div", { class: "meter", style: "margin-top:5px" }, [
          el("i", { style: `width:${Math.round((m.progress || 0) * 100)}%;`
            + `background: var(${m.met ? "--good" : "--series-1"})` }),
        ]));
        row.append(el("div", { class: "mneed", text: m.met
          ? `clears ${L.target.label} (${m.lower_is_better ? "\\u2264" : "\\u2265"} `
            + `${trim(m.threshold)} ${m.unit})`
          : `${L.target.label} needs ${m.lower_is_better ? "\\u2264" : "\\u2265"} `
            + `${trim(m.threshold)} ${m.unit}` }));
      } else {
        row.append(el("div", { class: "mneed", text: L.target
          ? `ungated at ${L.target.label}` : "no next rung" }));
      }
      row.append(el("div", { class: "mnote-s", text: m.note }));
      block.append(row);
    }
    grid.append(block);
  }
  host.append(grid);

  host.append(el("div", { class: "note", text:
    `${cur.measured} of ${cur.dimensions_total} dimensions were measured this session `
    + `(${L.min_dimensions} needed, or the reading is marked provisional). Coherence is `
    + "absent on purpose \\u2014 nothing here measures it, and a dimension scored on "
    + "impression would put back the drift this scale exists to remove. Interaction comes "
    + `from question practice and only counts while under ${L.interaction_max_age_days} days `
    + `old. Calibration ${L.calibration}: move a threshold and this whole line moves with `
    + "it, which is why the rows in level_history.csv carry the calibration that made them." }));
})();

/* ---------- session timeline ---------- */
(() => {
  const host = document.getElementById("timeline");
  const T = MODEL.timeline;
  if (!T.length) { host.hidden = true; return; }
  const linked = T.filter((e) => e.report).length;

  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "Session timeline" }),
      el("div", { class: "sub", text:
        "Everything dated, newest first \\u2014 the union of recordings and practice, because "
        + "practice happens on days with no recording and a chronology that dropped those "
        + "would suggest nothing was done on them." }),
    ]),
  ]));

  const t = el("table");
  t.append(el("thead", {}, [el("tr", {}, [
    el("th", { text: "Date" }), el("th", { class: "rung", text: "What happened" }),
    el("th", { class: "rung", text: "Mode" }), el("th", { text: "Reliable words" }),
    el("th", { text: "Mistakes / 1,000" }), el("th", { text: "Words lost" }),
    el("th", { text: "Practice" }), el("th", { text: "Scenarios" }),
  ])]));
  const body = el("tbody");
  for (const e of T.slice(0, TABLE_ROWS)) {
    const tags = el("div", { class: "tags" });
    if (e.recording) tags.append(el("span", { class: "chip", text: "recording" }));
    for (const mode of e.practice_modes)
      tags.append(el("span", { class: "chip",
        text: mode === "ask" ? "question practice" : "conversation practice" }));
    if (e.scenarios) tags.append(el("span", { class: "chip",
      text: `${e.scenarios} scenario${e.scenarios === 1 ? "" : "s"}` }));

    // A relative link to the archived report. It opens from the page's own
    // folder, so it keeps working as long as output/ sits beside analysis/.
    const date = e.report
      ? el("a", { class: "report", href: e.report, text: e.date })
      : el("span", { text: e.date });

    body.append(el("tr", {}, [
      el("th", { scope: "row" }, [date]),
      el("td", { class: "rung" }, [tags]),
      el("td", { class: "rung", text: e.mode || "\\u2014" }),
      el("td", { text: e.reliable_words === null ? "\\u2014" : int(e.reliable_words) }),
      el("td", { text: e.rate === null ? "\\u2014" : num(e.rate) }),
      el("td", { text: e.word_share === null || e.word_share === undefined
        ? "\\u2014" : `${Math.round(e.word_share * 100)}%` }),
      el("td", { text: e.practice_words ? `${int(e.practice_words)} words` : "\\u2014" }),
      el("td", { text: e.scenario_total ? `${e.scenario_met}/${e.scenario_total}` : "\\u2014" }),
    ]));
  }
  t.append(body);
  host.append(el("div", { class: "table-wrap" }, [t]));
  moreRows(host, T.length, TABLE_ROWS, "dated entries");
  host.append(el("div", { class: "note", text: linked
    ? `${linked} of ${T.length} dates link to their archived session report under `
      + "analysis/sessions/. The rest are practice-only days, which write no report."
    : "No archived reports were found to link to \\u2014 the page was built without knowing "
      + "where it would be written, so the dates here are plain text." }));
})();

/* chances — the denominator, and whether it earned its place */
(() => {
  const host = document.getElementById("chances");
  const C = MODEL.opportunity || {};
  if (!C.frames) { host.hidden = true; return; }

  const adopted = C.adopted || [];
  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "Chances" }),
      el("div", { class: "sub", text:
        "Everything else on this page is a numerator. “Six article mistakes per "
        + "thousand words” cannot say out of how many chances, because nothing counted "
        + "how many singular countable nouns were said — words spoken stood in for "
        + "chances, and on this history that substitution does not hold. A frame counts the "
        + "lines where the structure came up at all. It is a lexical match, not a parsed "
        + "one, so this is a proxy: it buys a series comparable with itself, not an exam "
        + "grade." }),
    ]),
  ]));

  host.append(el("div", { class: "notice", text:
    `${adopted.length} of ${C.rows.length} frames predict their category's errors better `
    + "than the word count does, and only those are used as a denominator. The rest keep "
    + "the per-1,000-words rate and say so — a frame that has not earned its place "
    + "cannot quietly make anything worse." }));

  const table = el("table");
  table.append(el("thead", {}, [el("tr", {}, [
    el("th", { text: "Pattern" }), el("th", { text: "Chances" }),
    el("th", { text: "Errors" }), el("th", { text: "Accuracy" }),
    el("th", { text: "Sessions" }), el("th", { class: "where", text: "Denominator" }),
  ])]));
  const body = el("tbody");
  for (const row of C.rows) {
    body.append(el("tr", {}, [
      el("th", { scope: "row" }, [
        el("div", { text: row.category }),
        row.note ? el("div", { class: "detail", style: "white-space:normal;max-width:52ch",
                               text: row.note }) : null,
      ]),
      el("td", { text: int(row.opportunities) }),
      el("td", { text: int(row.errors) }),
      el("td", { text: row.accuracy === null ? "—"
        : `${(row.accuracy * 100).toFixed(1)}%` }),
      el("td", { text: `${row.sessions}${row.enough ? "" : " · thin"}` }),
      el("td", { class: "where" }, [
        el("div", { text: row.adopted ? "chances" : "words" }),
        el("div", { class: "detail", style: "white-space:normal;max-width:44ch",
                    text: row.verdict }),
      ]),
    ]));
  }
  table.append(body);
  host.append(el("div", { class: "table-wrap" }, [table]));

  if ((C.frozen || []).length) host.append(el("div", { class: "note", text:
    "No chance to make these at all in the last three sessions, so their absence streaks are "
    + "frozen rather than earned: " + C.frozen.join(", ") + ". An absence streak built on "
    + "sessions where the structure never came up is not evidence of anything — which is "
    + "a thing this project previously worked out by hand, five sessions late." }));

  host.append(el("div", { class: "note", text:
    `A session needs ${C.min_opportunities} chances before its own accuracy is shown, and a `
    + `pattern needs ${C.min_sessions} sessions before the pooled figure reads as a trend. `
    + "Patterns with no frame are absent from this table entirely: some opportunities "
    + "— a bare singular noun, a noun used as a modifier — need a parser to spot, "
    + "and nothing here has one." }));
})();

/* about this page — what it can and cannot tell you, in one place */
(() => {
  const host = document.getElementById("about");
  const cats = MODEL.categories;
  const unsure = cats.filter((c) => c.direction === "not separable yet").length;
  const nodrill = (MODEL.ladder.states || {})["no-drill"] || 0;
  const thin = cats.filter((c) => c.thin).length;
  const E = MODEL.exposure || {};

  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "About this page" }),
      el("div", { class: "sub", text:
        "Every panel states its own caveat where it appears, which makes each one honest and "
        + "none of them a summary. This is the summary: how much the page as a whole "
        + "actually knows." }),
    ]),
  ]));

  const facts = [
    [`${MODEL.sessions.length} sessions`, `${MODEL.headline.first_date} to `
      + `${MODEL.headline.last_date}, ${int(MODEL.headline.reliable_words)} reliable words`],
    [`${unsure} of ${cats.length} trends cannot be told from chance`,
     "most of what is recorded here is a handful of events in a couple of thousand words, "
     + "and a difference of one or two instances is what a random process produces on its "
     + "own. A direction is only called when a two-sample Poisson test can separate it"],
    [`${thin} of ${cats.length} rankings rest on fewer than five instances`,
     "impact is severity against the square root of the rate, and severity is a judgment — "
     + "so a serious category seen three times can outrank one observed for months. That is "
     + "not wrong, but it is worth saying out loud"],
    [`${nodrill} of ${cats.length} patterns have no drill`,
     "so nothing above rung 3 can be measured for them: the only evidence on record is what "
     + "the recording caught"],
    ["The denominator is under test",
     (E.verdict || "not enough sessions to tell yet")
     + (E.narrow ? `. Session lengths span only ${E.spread}× so far, which is narrow `
                   + "enough to hide a real relationship" : "")],
  ];
  const list = el("div", { class: "facts" });
  for (const [head, body] of facts) {
    list.append(el("div", { class: "fact" }, [
      el("div", { class: "fact-head", text: head }),
      el("div", { class: "fact-body", text: body }),
    ]));
  }
  host.append(list);

  host.append(el("div", { class: "note", text:
    "Nothing here is an exam result. The level is a rung on a scale calibrated against this "
    + "speaker's own record; the chance-based accuracy is a lexical proxy; the mistake counts "
    + "are one coach's judgment, applied consistently. What the page is good at is noticing "
    + "that something has not moved in three sessions, which is the thing a person reading "
    + "their own notes reliably fails to notice." }));
})();

/* ---------- views and section nav ---------- */
//
// Two views, because one of them has to stay bounded. "Now" answers the
// questions asked on every open and must be the same three screens at session
// 12 and at session 300; "Evidence" holds everything that grows with the
// history — one row per session, one column per session — and is navigated
// rather than scrolled past.
//
// Both views are built eagerly and Evidence is hidden, not deferred. The cost
// is DOM nodes, which measured harmlessly (450ms to interactive at a hundred
// and fifty simulated sessions); the thing that was actually unbounded was
// *height*, and a hidden section has none. Deferring the build would mean
// restructuring every section into a function for a saving nothing has asked
// for yet. The charts still need one nudge on first show, because they size
// themselves from a container that is zero-width while hidden.
(() => {
  const host = document.getElementById("nav");
  const gaps = (MODEL.ladder.states || {})["automaticity-gap"] || 0;
  const criteria = MODEL.asking.totals;
  const chances = MODEL.opportunity || {};
  const badges = {
    actions: String(MODEL.actions.length),
    focus: String((MODEL.slate || []).length),
    working: String(MODEL.working.length),
    level: (MODEL.level.current || {}).label || "",
    heatmap: `${MODEL.categories.length}`,
    patterns: gaps ? `${gaps} gaps` : `${MODEL.categories.length}`,
    chances: chances.frames ? `${(chances.adopted || []).length}/${chances.rows.length}` : "",
    asking: criteria.total ? `${Math.round((criteria.met / criteria.total) * 100)}%` : "",
    quality: MODEL.speech.any_unreliable ? "check" : "",
    timeline: `${MODEL.timeline.length}`,
  };

  const panels = { now: document.getElementById("now"),
                   evidence: document.getElementById("evidence") };
  const tabs = { now: document.getElementById("view-now"),
                 evidence: document.getElementById("view-evidence") };
  let links = [];
  let observer = null;

  const buildNav = (view) => {
    host.textContent = "";
    links = [];
    for (const id of VIEWS[view]) {
      const section = document.getElementById(id);
      if (!section || section.hidden) continue;
      const link = el("a", { href: `#${id}` }, [
        el("span", { text: SECTION_LABELS[id] || id }),
        badges[id] ? el("span", { class: "badge", text: badges[id] }) : null,
      ]);
      host.append(link);
      links.push([link, section]);
    }
    if (observer) observer.disconnect();
    // Which section you are actually in, so a long page says where you are.
    const seen = new Map();
    observer = new IntersectionObserver((entries) => {
      for (const entry of entries) seen.set(entry.target, entry.intersectionRatio);
      let best = null, bestRatio = 0;
      for (const [link, section] of links) {
        const ratio = seen.get(section) || 0;
        if (ratio > bestRatio) { bestRatio = ratio; best = link; }
      }
      for (const [link] of links)
        link.setAttribute("aria-current", String(link === best && bestRatio > 0));
    }, { threshold: [0, 0.1, 0.25, 0.5, 0.75, 1] });
    for (const [, section] of links) observer.observe(section);
  };

  let built = { now: true, evidence: false };
  const show = (view, { scroll = true } = {}) => {
    for (const key of Object.keys(panels)) {
      panels[key].hidden = key !== view;
      tabs[key].setAttribute("aria-selected", String(key === view));
    }
    if (!built[view]) {
      built[view] = true;
      // First reveal, and the first time anything in here has a width. The
      // charts re-draw themselves: `responsive` watches each host with a
      // ResizeObserver, which fires on the 0 -> N transition without being
      // asked. (A `resize` event was dispatched here for a while; nothing in
      // this file listens for one, so it did nothing.) Scroll position is the
      // part that does need doing, because it cannot be set while hidden.
      requestAnimationFrame(() => {
        for (const box of panels[view].querySelectorAll(".heat-scroll"))
          box.scrollLeft = box.scrollWidth;
      });
    }
    buildNav(view);
    try { sessionStorage.setItem("vge-view", view); } catch (e) { /* no-op */ }
    if (scroll) window.scrollTo({ top: 0, behavior: "instant" });
  };

  tabs.now.addEventListener("click", () => show("now"));
  tabs.evidence.addEventListener("click", () => show("evidence"));

  // A link from Now into an Evidence section has to switch views first, or it
  // scrolls to something that is not on screen.
  const viewOf = (id) => VIEWS.evidence.includes(id) ? "evidence" : "now";
  document.addEventListener("click", (ev) => {
    const anchor = ev.target.closest("a[href^='#']");
    if (!anchor) return;
    const id = anchor.getAttribute("href").slice(1);
    const section = document.getElementById(id) || document.querySelector(`[id='${id}']`);
    if (!section) return;
    const wanted = viewOf(section.closest("section[id]") ?
      section.closest("section[id]").id : id);
    if (panels[wanted] && panels[wanted].hidden) {
      ev.preventDefault();
      show(wanted, { scroll: false });
      requestAnimationFrame(() => section.scrollIntoView({ block: "start" }));
    }
  });

  let start = "now";
  try { start = sessionStorage.getItem("vge-view") || "now"; } catch (e) { /* no-op */ }
  // A deep link wins over the remembered view: it is a more specific request.
  if (location.hash) {
    const target = document.querySelector(location.hash);
    const section = target && target.closest("section[id]");
    if (section) start = viewOf(section.id);
  }
  show(start, { scroll: false });
  if (location.hash) {
    const target = document.querySelector(location.hash);
    if (target) requestAnimationFrame(() => target.scrollIntoView({ block: "start" }));
  }
})();

// Every table is built by the time the section IIFEs above have run.
labelCells(document);

/* theme */
document.getElementById("theme").addEventListener("click", () => {
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  const current = document.documentElement.dataset.theme || (dark ? "dark" : "light");
  document.documentElement.dataset.theme = current === "dark" ? "light" : "dark";
  window.dispatchEvent(new Event("resize"));
});
</script>
</body>
</html>
"""
