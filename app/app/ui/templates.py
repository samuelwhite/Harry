from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

CSS = """
:root {
  --bgA: #0b1220;
  --bgB: #0a1830;
  --bgC: #0b1a2b;
  --panel: rgba(255,255,255,0.05);
  --panel-strong: rgba(255,255,255,0.08);
  --panel-soft: rgba(255,255,255,0.035);
  --stroke: rgba(255,255,255,0.12);
  --stroke-strong: rgba(255,255,255,0.18);
  --text: rgba(255,255,255,0.92);
  --muted: rgba(255,255,255,0.62);

  --ok: #34d399;
  --info: #60a5fa;
  --warn: #fbbf24;
  --bad: #fb7185;
  --stale: #fb7185;

  --sidebar-w: 280px;
  --radius: 18px;
  --shadow: 0 18px 50px rgba(0,0,0,0.35);
}

* { box-sizing: border-box; }

html, body {
  margin: 0;
  padding: 0;
  min-height: 100%;
  overflow-x: hidden;
  scroll-behavior: smooth;
}

body {
  min-height: 100vh;
  font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
  background:
    radial-gradient(900px 700px at 20% 18%, rgba(90,110,255,0.24), rgba(10,18,32,0.0) 60%),
    radial-gradient(900px 700px at 82% 10%, rgba(120,70,255,0.18), rgba(10,18,32,0.0) 55%),
    radial-gradient(900px 700px at 60% 92%, rgba(0,210,255,0.10), rgba(10,18,32,0.0) 55%),
    linear-gradient(180deg, var(--bgB) 0%, var(--bgA) 48%, #070b14 100%);
  background-attachment: fixed;
  color: var(--text);
}

a { color: inherit; text-decoration: none; }
a:hover { text-decoration: underline; }

button,
input[type="submit"],
input[type="button"] {
  font: inherit;
}

.shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: var(--sidebar-w) minmax(0, 1fr);
}

.sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
  padding: 20px 16px 20px 20px;
  border-right: 1px solid rgba(255,255,255,0.08);
  background: linear-gradient(180deg, rgba(8,14,28,0.84), rgba(8,14,28,0.66));
  backdrop-filter: blur(10px);
}

.sidebar-inner {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.brand {
  padding: 14px 14px 12px;
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 18px;
  background: rgba(255,255,255,0.05);
  box-shadow: var(--shadow);
}

.brand-title {
  font-size: 1.25rem;
  font-weight: 950;
  letter-spacing: 0.8px;
}

.brand-sub {
  margin-top: 6px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.4;
}

.sidebar-group {
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 18px;
  background: rgba(255,255,255,0.035);
  padding: 12px;
}

.sidebar-label {
  font-size: 12px;
  color: rgba(255,255,255,0.66);
  font-weight: 900;
  letter-spacing: 0.4px;
  text-transform: uppercase;
  margin-bottom: 10px;
}

.sidebar-links {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sidebar-link {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 40px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid transparent;
  color: rgba(255,255,255,0.90);
  font-size: 14px;
  font-weight: 800;
  transition: background 0.12s ease, border-color 0.12s ease, transform 0.12s ease;
}

.sidebar-link:hover {
  text-decoration: none;
  background: rgba(255,255,255,0.07);
  border-color: rgba(255,255,255,0.10);
}

.sidebar-link.active {
  background: rgba(255,255,255,0.09);
  border-color: rgba(255,255,255,0.10);
  box-shadow: none;
}

.sidebar-link.sub {
  color: rgba(255,255,255,0.78);
  font-size: 13px;
  font-weight: 700;
  padding-left: 18px;
}

.sidebar-meta {
  margin-top: auto;
  padding: 12px;
  color: rgba(255,255,255,0.58);
  font-size: 12px;
  line-height: 1.45;
}

.main {
  min-width: 0;
  padding: 18px;
}

.main-inner {
  width: 100%;
  max-width: 1320px;
  margin: 0 auto;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 18px;
  padding: 14px 16px;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 20px;
  background: rgba(11,18,32,0.72);
  box-shadow: 0 16px 40px rgba(0,0,0,0.26);
  backdrop-filter: blur(10px);
}

.topbar-left {
  min-width: 0;
}

.h1 {
  font-size: clamp(1.95rem, 4.2vw, 3rem);
  font-weight: 900;
  letter-spacing: 0.2px;
  line-height: 1.06;
  margin: 0 0 8px;
}

.sub {
  color: rgba(255,255,255,0.72);
  font-size: clamp(0.82rem, 1.5vw, 0.95rem);
  margin: 0;
  display: flex;
  gap: 8px 12px;
  flex-wrap: wrap;
}

.topbar-right {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.menuwrap {
  position: relative;
}

.menubtn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 46px;
  height: 46px;
  border-radius: 14px;
  border: 1px solid rgba(255,255,255,0.12);
  background: rgba(255,255,255,0.07);
  color: var(--text);
  cursor: pointer;
  transition: background 0.12s ease, border-color 0.12s ease, transform 0.12s ease;
}

.menubtn:hover {
  background: rgba(255,255,255,0.11);
  border-color: rgba(255,255,255,0.18);
}

.menubtn:focus-visible {
  outline: 2px solid rgba(96,165,250,0.7);
  outline-offset: 2px;
}

.menu {
  position: absolute;
  right: 0;
  top: calc(100% + 10px);
  min-width: 220px;
  padding: 10px;
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 16px;
  background: rgba(11,18,32,0.95);
  box-shadow: 0 18px 50px rgba(0,0,0,0.35);
  backdrop-filter: blur(12px);
  display: none;
}

.menu.open {
  display: block;
}

.menu-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.menu-item {
  display: flex;
  align-items: center;
  min-height: 40px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid transparent;
  color: rgba(255,255,255,0.90);
  font-size: 13px;
  font-weight: 800;
}

.menu-item:hover {
  text-decoration: none;
  background: rgba(255,255,255,0.08);
  border-color: rgba(255,255,255,0.10);
}

.content {
  min-width: 0;
}

.section {
  margin: clamp(12px, 2vw, 18px) 0;
  scroll-margin-top: 96px;
}

.sectionhead {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 12px;
  flex-wrap: wrap;
  margin: 0 0 10px;
}

.h2 {
  font-size: clamp(1.05rem, 2vw, 1.35rem);
  font-weight: 950;
  letter-spacing: 0.25px;
  margin: 0;
}

.h2sub {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: clamp(0.8rem, 1.4vw, 0.95rem);
  font-style: italic;
}

.divider {
  height: 1px;
  background: rgba(255,255,255,0.08);
  margin: 14px 0 18px;
}

.topwarnwrap {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin: 10px 0 16px;
}

.topwarn {
  font-size: clamp(0.8rem, 1.5vw, 0.92rem);
  padding: 9px 12px;
  border-radius: 999px;
  border: 1px solid var(--stroke);
  background: rgba(255,255,255,0.05);
  box-shadow: 0 10px 30px rgba(0,0,0,0.30);
}

.topwarn.bad, .topwarn.stale {
  border-color: rgba(251, 113, 133, 0.35);
  background: rgba(251, 113, 133, 0.12);
}

.topwarn.warn {
  border-color: rgba(251, 191, 36, 0.35);
  background: rgba(251, 191, 36, 0.12);
}

.nodes {
  display: grid;
  gap: 18px;
  grid-template-columns: 1fr;
}

@media (min-width: 1600px) {
  .nodes { grid-template-columns: 1fr 1fr; }
}

.card {
  border: 1px solid var(--stroke);
  background: linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.04));
  border-radius: clamp(14px, 2vw, 18px);
  padding: clamp(12px, 2vw, 16px);
  box-shadow: 0 18px 50px rgba(0,0,0,0.40);
  backdrop-filter: blur(6px);
  min-width: 0;
}

.cardtop {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex-wrap: wrap;
}

.nodename {
  font-size: clamp(1.15rem, 4vw, 1.55rem);
  font-weight: 900;
}

.model {
  font-size: clamp(0.95rem, 2vw, 1.15rem);
  font-weight: 700;
  color: rgba(255,255,255,0.70);
}

.nodever {
  margin-top: 4px;
  font-size: 10px;
  color: rgba(255,255,255,0.60);
}

.nodever.ok { color: rgba(255,255,255,0.68); }
.nodever.behind { color: rgba(251,191,36,0.92); }
.nodever.unknown { color: rgba(255,255,255,0.50); }

.subtitle {
  margin-top: 4px;
  font-size: clamp(0.82rem, 1.4vw, 0.95rem);
  color: rgba(255,255,255,0.72);
  font-style: italic;
}

.pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 999px;
  border: 1px solid var(--stroke);
  background: rgba(255,255,255,0.05);
  font-size: clamp(0.74rem, 1.35vw, 0.88rem);
  white-space: nowrap;
  margin: 0 8px 8px 0;
}

.pill.neutral { background: rgba(255,255,255,0.045); }

.pill.warn {
  border-color: rgba(251,191,36,0.35);
  background: rgba(251,191,36,0.10);
}

.pill.bad {
  border-color: rgba(251,113,133,0.35);
  background: rgba(251,113,133,0.10);
}

.dot {
  width: 12px;
  height: 12px;
  border-radius: 999px;
  background: rgba(255,255,255,0.40);
  box-shadow: 0 0 0 4px rgba(255,255,255,0.06);
  display: inline-block;
}

.dot.ok { background: var(--ok); box-shadow: 0 0 0 4px rgba(52,211,153,0.18); }
.dot.warn { background: var(--warn); box-shadow: 0 0 0 4px rgba(251,191,36,0.18); }
.dot.bad { background: var(--bad); box-shadow: 0 0 0 4px rgba(251,113,133,0.18); }
.dot.stale { background: var(--stale); box-shadow: 0 0 0 4px rgba(251,113,133,0.18); }
.dot.neutral { background: rgba(255,255,255,0.55); box-shadow: 0 0 0 4px rgba(255,255,255,0.10); }

.row {
  display: grid;
  gap: 12px;
}

.row2 {
  grid-template-columns: 1fr 220px 1.1fr;
}

.row3 {
  grid-template-columns: 1.2fr 0.8fr 0.9fr;
  margin-top: 12px;
}

.kvbox, .rammeta, .panel {
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 14px;
  background: rgba(0,0,0,0.16);
  padding: clamp(10px, 1.5vw, 12px);
  min-width: 0;
}

.panel { min-height: 140px; }

.k {
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 8px;
}

.v.big {
  font-size: clamp(1.08rem, 1.9vw, 1.35rem);
  font-weight: 900;
  color: rgba(255,255,255,0.96);
}

.ramtop {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 10px;
}

.ramright {
  font-size: clamp(1rem, 2vw, 1.15rem);
  font-weight: 900;
}

.rambottom {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-top: 6px;
  color: rgba(255,255,255,0.62);
  font-size: 12px;
}

.rightmuted { text-align: right; }

.ph {
  font-size: 12px;
  color: rgba(255,255,255,0.75);
  letter-spacing: 0.4px;
  font-weight: 900;
  margin-bottom: 10px;
}

.bar {
  height: 10px;
  border-radius: 999px;
  background: rgba(255,255,255,0.09);
  overflow: hidden;
  border: 1px solid rgba(255,255,255,0.08);
  margin-top: 8px;
}

.bar.ram { height: 12px; }

.fill {
  height: 100%;
  width: 0%;
  background: linear-gradient(90deg, rgba(52,211,153,0.95), rgba(52,211,153,0.40));
}

.muted {
  color: rgba(255,255,255,0.62);
  font-size: 13px;
}

.gpuitem {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 7px 0;
  border-bottom: 1px solid rgba(255,255,255,0.08);
}

.gpuitem:last-child { border-bottom: none; }

.gpuname {
  font-weight: 900;
  min-width: 0;
}

.gpumeta {
  color: rgba(255,255,255,0.72);
  font-size: 12.5px;
  text-align: right;
}

.adviceitem {
  display: flex;
  gap: 10px;
  align-items: baseline;
  padding: 6px 0;
  border-bottom: 1px solid rgba(255,255,255,0.08);
}

.adviceitem:last-child { border-bottom: none; }

.tag {
  font-size: 12px;
  font-weight: 900;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,0.12);
  background: rgba(255,255,255,0.06);
  text-transform: lowercase;
  min-width: 52px;
  text-align: center;
}

.tag.ok { border-color: rgba(52,211,153,0.35); background: rgba(52,211,153,0.10); }
.tag.info { border-color: rgba(96,165,250,0.35); background: rgba(96,165,250,0.10); }
.tag.warn { border-color: rgba(251,191,36,0.35); background: rgba(251,191,36,0.10); }
.tag.bad { border-color: rgba(251,113,133,0.35); background: rgba(251,113,133,0.10); }

.msg {
  font-size: 13px;
  color: rgba(255,255,255,0.88);
}

.trendrow {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(3, 1fr);
  width: 100%;
  margin-top: 12px;
}

.trenditem {
  border: 1px solid rgba(255,255,255,0.10);
  background: rgba(255,255,255,0.04);
  border-radius: 14px;
  padding: 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.tk {
  font-weight: 900;
  white-space: nowrap;
}

.tv {
  flex: 1;
  min-width: 0;
  display: flex;
  justify-content: flex-end;
}

.tv svg {
  display: block;
  width: 100%;
  height: auto;
  max-width: 100%;
}

.mapwrap, .invwrap, .advwrap {
  border: 1px solid var(--stroke);
  background: rgba(255,255,255,0.04);
  border-radius: clamp(14px, 2vw, 18px);
  padding: clamp(12px, 2vw, 16px);
  box-shadow: 0 18px 50px rgba(0,0,0,0.35);
  margin: 0;
}

.mapwrap {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.mapwrap svg {
  display: block;
  min-width: 720px;
}

.invwrap {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.trendcards {
  display: grid;
  gap: 16px;
  grid-template-columns: 1fr;
}

.trendcard {
  overflow: hidden;
}

.trendpills {
  justify-content: flex-end;
}

.trendchartrow {
  margin-top: 12px;
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 14px;
  background: rgba(255,255,255,0.03);
  padding: 12px;
}

.trendcharthead {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: baseline;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.trendchartlabel {
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.25px;
  color: rgba(255,255,255,0.82);
}

.trendchartmeta {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 11.5px;
  color: rgba(255,255,255,0.60);
}

.trendchartbody {
  width: 100%;
  min-height: 110px;
}

.trendchartfoot {
  margin-top: 6px;
  text-align: center;
  font-size: 11px;
  color: rgba(255,255,255,0.42);
}

.widechart {
  display: block;
  width: 100%;
  height: 110px;
}

.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.btn,
button.btn,
input[type="submit"].btn,
input[type="button"].btn,
form .btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 40px;
  padding: 8px 12px;
  border-radius: 12px;
  border: 1px solid rgba(255,255,255,0.10);
  background: rgba(255,255,255,0.07);
  color: rgba(255,255,255,0.92);
  font-size: clamp(0.78rem, 1.45vw, 0.92rem);
  font-weight: 800;
  text-decoration: none;
  cursor: pointer;
  appearance: none;
  -webkit-appearance: none;
}

.btn:hover,
button.btn:hover,
input[type="submit"].btn:hover,
input[type="button"].btn:hover,
form .btn:hover {
  background: rgba(255,255,255,0.11);
  border-color: rgba(255,255,255,0.16);
  text-decoration: none;
}

.btn:focus-visible,
button.btn:focus-visible,
input[type="submit"].btn:focus-visible,
input[type="button"].btn:focus-visible,
form .btn:focus-visible {
  outline: 2px solid rgba(96,165,250,0.7);
  outline-offset: 2px;
}

.legend {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid rgba(255,255,255,0.08);
}

.legend .item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,0.10);
  background: rgba(255,255,255,0.04);
  font-size: 12px;
  color: rgba(255,255,255,0.86);
}

.legend .mut { color: rgba(255,255,255,0.62); }

table.inv {
  width: 100%;
  min-width: 760px;
  border-collapse: collapse;
}

.inv th, .inv td {
  border-bottom: 1px solid rgba(255,255,255,0.08);
  padding: 10px 8px;
  text-align: left;
  vertical-align: top;
  font-size: 12.5px;
}

.inv th {
  color: rgba(255,255,255,0.70);
  font-weight: 900;
  font-size: 12px;
  letter-spacing: 0.3px;
}

.inv tr:last-child td { border-bottom: none; }
.inv .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }
.inv .right { text-align: right; }
.inv .status { white-space: nowrap; }
.inv .advicecol { white-space: nowrap; }

.badgetxt {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 9px;
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,0.10);
  background: rgba(255,255,255,0.04);
  font-size: 11.5px;
  font-weight: 900;
  letter-spacing: 0.2px;
}

.badgetxt.ok { border-color: rgba(52,211,153,0.25); background: rgba(52,211,153,0.08); }
.badgetxt.warn { border-color: rgba(251,191,36,0.35); background: rgba(251,191,36,0.10); }
.badgetxt.bad { border-color: rgba(251,113,133,0.35); background: rgba(251,113,133,0.10); }
.badgetxt.stale { border-color: rgba(251,113,133,0.35); background: rgba(251,113,133,0.10); }

.advrow {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid rgba(255,255,255,0.08);
}

.advrow:last-child { border-bottom: none; }

.advleft { min-width: 0; }

.advnode {
  font-weight: 950;
  letter-spacing: 0.2px;
}

.advmsg {
  margin-top: 4px;
  color: rgba(255,255,255,0.88);
  font-size: 15px;
  line-height: 1.6;
}

.advright {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.advsmall {
  color: rgba(255,255,255,0.62);
  font-size: 12px;
}

.details {
  margin-top: 12px;
  border-top: 1px solid rgba(255,255,255,0.08);
  padding-top: 10px;
}

.details summary {
  cursor: pointer;
  list-style: none;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-weight: 900;
  color: rgba(255,255,255,0.86);
  padding: 8px 10px;
  border-radius: 12px;
  border: 1px solid rgba(255,255,255,0.10);
  background: rgba(255,255,255,0.04);
}

.details summary::-webkit-details-marker { display:none; }

.details .detailsmuted {
  color: rgba(255,255,255,0.62);
  font-weight: 600;
  font-size: 12.5px;
}

.linkline {
  stroke: rgba(255,255,255,0.18);
  stroke-width: 2;
  fill: none;
}

.linkline.pulse {
  stroke: rgba(255,255,255,0.55);
  stroke-width: 2.6;
  filter: drop-shadow(0 0 6px rgba(255,255,255,0.18));
  stroke-dasharray: 10 999;
  animation: pulseDash 1.1s ease-out 1;
}

@keyframes pulseDash {
  from { stroke-dashoffset: 0; opacity: 1; }
  to   { stroke-dashoffset: -220; opacity: 0.25; }
}

.nodeDot.ping {
  animation: dotPing 0.75s ease-out 1;
}

@keyframes dotPing {
  0%   { filter: drop-shadow(0 0 0 rgba(255,255,255,0.0)); transform: scale(1); }
  35%  { filter: drop-shadow(0 0 10px rgba(255,255,255,0.22)); transform: scale(1.12); }
  100% { filter: drop-shadow(0 0 0 rgba(255,255,255,0.0)); transform: scale(1); }
}

.stats {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.stat {
  border: 1px solid rgba(255,255,255,0.10);
  background: linear-gradient(180deg, rgba(255,255,255,0.07), rgba(255,255,255,0.035));
  border-radius: 16px;
  padding: clamp(12px, 2vw, 16px);
  box-shadow: 0 14px 40px rgba(0,0,0,0.25);
}

.statk {
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.25px;
}

.statv {
  margin-top: 6px;
  font-size: clamp(1.5rem, 4vw, 2rem);
  font-weight: 950;
  line-height: 1.1;
}

.cardgrid {
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.kvgrid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 12px;
}

.kv {
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 14px;
  background: rgba(0,0,0,0.15);
  padding: 12px;
  min-width: 0;
}

.kv .k {
  margin-bottom: 6px;
  font-size: 11.5px;
  color: var(--muted);
  font-weight: 800;
  letter-spacing: 0.25px;
}

.kv .v {
  font-size: 13px;
  color: rgba(255,255,255,0.92);
  word-break: break-word;
}

.splitcols {
  display: grid;
  gap: 12px;
  grid-template-columns: 1fr 1fr;
  margin-top: 12px;
}

.subcard {
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 14px;
  background: rgba(255,255,255,0.03);
  padding: 12px;
  min-width: 0;
}

.subcardtitle {
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.3px;
  color: rgba(255,255,255,0.78);
  margin-bottom: 8px;
}

.subcardbody {
  font-size: 12.5px;
  color: rgba(255,255,255,0.88);
  line-height: 1.5;
  word-break: break-word;
}

.empty {
  border: 1px dashed rgba(255,255,255,0.16);
  border-radius: 16px;
  padding: 18px;
  color: var(--muted);
  background: rgba(255,255,255,0.025);
}

.footerline {
  margin-top: 18px;
  padding-top: 12px;
  border-top: 1px solid rgba(255,255,255,0.08);
  color: rgba(255,255,255,0.68);
  font-size: 12px;
  text-align: center;
}

svg a { cursor: pointer; pointer-events: auto; }
svg text { pointer-events: auto; }

@media (max-width: 1180px) {
  .shell {
    grid-template-columns: 1fr;
  }

  .sidebar {
    position: relative;
    top: auto;
    height: auto;
    border-right: none;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    padding: 14px;
  }

  .main {
    padding-top: 14px;
  }

  .topbar {
    position: relative;
    top: auto;
  }
}

@media (max-width: 980px) {
  .stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .row2,
  .row3,
  .cardgrid,
  .kvgrid,
  .splitcols,
  .nodes {
    grid-template-columns: 1fr;
  }

  .sectionhead {
    align-items: stretch;
  }

  .actions {
    width: 100%;
  }

  .actions .btn {
    flex: 1 1 auto;
  }

  .advrow {
    flex-direction: column;
    align-items: flex-start;
  }

  .advright {
    justify-content: flex-start;
  }
}

@media (max-width: 720px) {
  .main {
    padding: 10px;
  }

  .topbar {
    flex-direction: column;
    align-items: stretch;
  }

  .topbar-right {
    justify-content: flex-end;
  }

  .topwarn {
    width: 100%;
    border-radius: 16px;
  }

  .card,
  .mapwrap,
  .invwrap,
  .advwrap {
    padding: 12px;
    box-shadow: 0 12px 34px rgba(0,0,0,0.28);
  }

  .cardtop {
    flex-direction: column;
    align-items: stretch;
  }

  .title {
    gap: 8px;
  }

  .pill {
    white-space: normal;
  }

  .trendrow {
    grid-template-columns: 1fr;
  }

  .trendpills {
    justify-content: flex-start;
  }

  .trendcharthead {
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
  }

  .widechart {
    height: 100px;
  }

  table.inv {
    min-width: 680px;
  }

  .inv th,
  .inv td {
    padding: 9px 7px;
    font-size: 12px;
  }

  .legend {
    gap: 8px;
  }

  .legend .item {
    width: 100%;
    justify-content: flex-start;
  }

  .details summary {
    width: 100%;
    justify-content: space-between;
  }
}

@media (max-width: 480px) {
  .stats {
    grid-template-columns: 1fr;
  }

  .sub {
    gap: 4px 10px;
  }

  .pill {
    font-size: 0.76rem;
    padding: 6px 9px;
  }

  .btn {
    width: 100%;
  }

  table.inv {
    min-width: 620px;
  }

  .mapwrap svg {
    min-width: 640px;
  }

  .footerline {
    font-size: 11px;
  }

  .menu {
    left: 0;
    right: 0;
    min-width: 0;
  }
}
"""

JS_PULSE = r"""
(() => {
  const POLL_MS = 9000;
  const MAX_ANIM_MS = 1200;

  let lastSeen = {};
  let started = false;

  function safeId(node) {
    return String(node).replace(/[^a-zA-Z0-9_-]/g, "_");
  }

  function trigger(node) {
    const id = safeId(node);
    const path = document.getElementById(`link-${id}`);
    const dot  = document.getElementById(`dot-${id}`);

    if (path) {
      path.classList.remove("pulse");
      void path.getBoundingClientRect();
      path.classList.add("pulse");
      setTimeout(() => path.classList.remove("pulse"), MAX_ANIM_MS);
    }

    if (dot) {
      dot.classList.remove("ping");
      void dot.getBoundingClientRect();
      dot.classList.add("ping");
      setTimeout(() => dot.classList.remove("ping"), 900);
    }
  }

  async function poll() {
    try {
      const r = await fetch("/inventory.json", { cache: "no-store" });
      if (!r.ok) return;
      const data = await r.json();
      const nodes = (data && data.nodes) ? data.nodes : [];

      const next = {};
      const changed = [];

      for (const n of nodes) {
        const node = n.node;
        const ts = n.last_seen || "";
        next[node] = ts;

        if (started && lastSeen[node] && ts && ts !== lastSeen[node]) {
          changed.push(node);
        }
      }

      lastSeen = next;
      if (!started) started = true;

      for (const node of changed) trigger(node);
    } catch (_) {
    }
  }

  function initMenu() {
    const btn = document.querySelector("[data-menu-toggle]");
    const menu = document.querySelector("[data-menu]");
    if (!btn || !menu) return;

    function closeMenu() {
      menu.classList.remove("open");
      btn.setAttribute("aria-expanded", "false");
    }

    function openMenu() {
      menu.classList.add("open");
      btn.setAttribute("aria-expanded", "true");
    }

    btn.addEventListener("click", (e) => {
      e.preventDefault();
      if (menu.classList.contains("open")) closeMenu();
      else openMenu();
    });

    document.addEventListener("click", (e) => {
      if (!menu.contains(e.target) && !btn.contains(e.target)) {
        closeMenu();
      }
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeMenu();
    });
  }

  initMenu();
  poll();
  setInterval(poll, POLL_MS);
})();
"""

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _html_escape(s: str) -> str:
    s = "" if s is None else str(s)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )

def _safe_dom_id(s: str) -> str:
    out = []
    for ch in (s or ""):
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out) or "node"

def _fmt_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return "—"
    return dt.astimezone(timezone.utc).strftime("%a %d %b %Y %H:%M")

def _ago(dt: Optional[datetime]) -> str:
    if not dt:
        return "unknown"
    now = _utcnow()
    delta = now - dt
    if delta.total_seconds() < -60:
        return "in the future (clock?)"
    if delta.total_seconds() < 60:
        return "just now"
    mins = int(delta.total_seconds() // 60)
    if mins < 60:
        return f"{mins}m ago"
    hrs = mins // 60
    if hrs < 24:
        return f"{hrs}h ago"
    days = hrs // 24
    return f"{days}d ago"

def _sev_dot(sev: str) -> str:
    sev = (sev or "ok").lower()
    if sev == "bad":
        return "dot bad"
    if sev == "warn":
        return "dot warn"
    if sev == "stale":
        return "dot stale"
    if sev == "neutral":
        return "dot neutral"
    return "dot ok"

def _pill(sev: str, text: str) -> str:
    sev = (sev or "neutral").lower()
    return f'<span class="pill {sev}"><span class="{_sev_dot(sev)}"></span>{_html_escape(text)}</span>'

def _badge_text(sev: str, label: str) -> str:
    sev = (sev or "ok").lower()
    cls = sev if sev in ("ok", "warn", "bad", "stale") else "ok"
    return f'<span class="badgetxt {cls}">{_html_escape(label)}</span>'

def page_html(title: str, body: str, extra_js: str = "") -> str:
    script = f"<script>{extra_js}</script>" if extra_js else ""
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{_html_escape(title)}</title>
  <style>{CSS}</style>
</head>
<body>
  {body}
  {script}
</body>
</html>
"""

def _render_sidebar(sidebar_sections: list[dict], active_page: str) -> str:
    groups = []

    for section in sidebar_sections:
        label = _html_escape(section.get("label") or "")
        items = section.get("items") or []
        links = []

        for item in items:
            item_label = _html_escape(item.get("label") or "")
            href = _html_escape(item.get("href") or "#")
            is_active = bool(item.get("active")) or (item.get("page") == active_page)
            is_sub = bool(item.get("sub"))
            cls = "sidebar-link"
            if is_sub:
                cls += " sub"
            if is_active:
                cls += " active"
            links.append(f'<a class="{cls}" href="{href}">{item_label}</a>')

        groups.append(
            f"""
<div class="sidebar-group">
  <div class="sidebar-label">{label}</div>
  <div class="sidebar-links">
    {''.join(links)}
  </div>
</div>
"""
        )

    return "".join(groups)

def _render_actions(actions: list[dict]) -> str:
    if not actions:
        return ""

    items = []
    for action in actions:
        label = _html_escape(action.get("label") or "")
        href = _html_escape(action.get("href") or "#")
        items.append(f'<a class="menu-item" href="{href}">{label}</a>')

    return f"""
<div class="menuwrap">
  <button class="menubtn" type="button" data-menu-toggle aria-expanded="false" aria-label="Open actions menu">
    ☰
  </button>
  <div class="menu" data-menu>
    <div class="menu-section">
      {''.join(items)}
    </div>
  </div>
</div>
"""

def render_shell(
    *,
    title: str,
    active_page: str,
    page_title: str,
    page_subtitle: str,
    sidebar_sections: list[dict],
    actions: list[dict],
    content: str,
    extra_js: str = "",
    sidebar_footer: str = "",
) -> str:
    body = f"""
<div class="shell">
  <aside class="sidebar">
    <div class="sidebar-inner">
      <div class="brand">
        <div class="brand-title">HARRY</div>
        <div class="brand-sub">HARdware Review buddY</div>
      </div>

      {_render_sidebar(sidebar_sections, active_page=active_page)}

      <div class="sidebar-meta">
        Quiet infrastructure.<br/>
        Boring is good.
        {f'<div style="margin-top:10px; padding-top:10px; border-top:1px solid rgba(255,255,255,0.08);">{sidebar_footer}</div>' if sidebar_footer else ''}
      </div>
    </div>
  </aside>

  <main class="main">
    <div class="main-inner">
      <div class="topbar">
        <div class="topbar-left">
          <div class="h1">{_html_escape(page_title)}</div>
          <div class="sub">{page_subtitle}</div>
        </div>
        <div class="topbar-right">
          {_render_actions(actions)}
        </div>
      </div>

      <div class="content">
        {content}
      </div>
    </div>
  </main>
</div>
"""
    merged_js = JS_PULSE
    if extra_js:
        merged_js += "\n" + extra_js
    return page_html(title, body, extra_js=merged_js)
