export const ARCHIVE_HOME_EXPLORER_CSS = String.raw`:root {
      --archive-header-brand-size: 16px;
      --archive-header-nav-size: 11px;
      --archive-header-control-size: 11px;
      --archive-header-control-letter-spacing: 0.07em;
      --bg: #0a0a0a;
      --paper: #111111;
      --paper-2: #161616;
      --ink: #f3f3f3;
      --muted: #ababab;
      --lime: #d8ff5a;
      --violet: #7f51ff;
      --line: #2c2c2c;
      --line-soft: #242424;
      --radius: 8px;
    }

    * { box-sizing: border-box; }

    html, body {
      margin: 0;
      padding: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: 'Space Mono', monospace;
      scroll-behavior: smooth;
    }

    a { color: inherit; text-decoration: none; }

    .shell { max-width: var(--page-max-width); margin: 0 auto; padding: calc(var(--topbar-height) + var(--page-below-topbar)) var(--page-gutter) 72px; }

    .brand,
    .logo {
      flex: 0 0 auto;
      white-space: nowrap;
    }

    .brand {
      font-family: 'Space Mono', monospace;
      font-size: var(--archive-header-brand-size);
      line-height: 1;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: #d8d8d8;
      padding-bottom: 2px;
    }

    .logo {
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: #d8d8d8;
    }

    .section {
      border: 1px solid var(--line);
      background: var(--paper);
      margin-top: var(--page-gutter);
    }

    .section.dark { background: #0f0f0f; }

    .section-inner { padding: var(--page-pad-y) var(--page-pad); }

    .section-head {
      display: grid;
      grid-template-columns: 1.5fr 1fr;
      gap: 20px;
      align-items: end;
      margin-bottom: 18px;
    }

    .section-head h2 {
      margin: 0;
      font-family: 'Manrope', sans-serif;
      font-size: clamp(38px, 7.6vw, 82px);
      line-height: 0.88;
      letter-spacing: -0.04em;
      text-transform: uppercase;
      color: #fff;
    }

    .section-head p {
      margin: 0;
      justify-self: end;
      max-width: 460px;
      font-size: 11px;
      line-height: 1.8;
      color: var(--muted);
    }

    .kicker {
      display: inline-flex;
      border: 1px solid var(--line);
      padding: 5px 10px;
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.09em;
      text-transform: uppercase;
      margin-bottom: 10px;
      color: #d8d8d8;
    }

    .hero {
      background: #101010;
      border: 1px solid #2a2a2a;
      margin-top: 10px;
      position: relative;
      overflow: hidden;
    }

    .hero .section-inner {
      position: relative;
      padding-top: var(--page-pad-y);
      padding-bottom: clamp(14px, 2.4vw, 24px);
      display: grid;
      gap: 12px;
    }

    .hero .kicker {
      position: relative;
      margin-bottom: 0;
      z-index: 4;
      justify-self: start;
      width: fit-content;
      max-width: 100%;
    }

    .hero-grid {
      display: grid;
      grid-template-columns: 1.6fr 1fr;
      gap: 12px;
      align-items: start;
    }

    .hero-main {
      display: grid;
      grid-template-rows: minmax(0, 1fr) auto;
      min-height: 0;
    }

    .hero-visual {
      height: clamp(250px, 34vh, 360px);
      min-height: 0;
      position: relative;
      border: 1px solid var(--line);
      background: #0d0d0d;
      overflow: hidden;
    }

    .hero-visual::after {
      content: '';
      position: absolute;
      inset: 0;
      background: linear-gradient(to top, rgba(0, 0, 0, 0.62) 0%, rgba(0, 0, 0, 0.16) 52%, rgba(0, 0, 0, 0.05) 100%);
      pointer-events: none;
      z-index: 1;
    }

    .hero-visual img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      object-position: center 24%;
      filter: grayscale(20%);
      display: block;
      position: relative;
      z-index: 0;
    }

    .hero-title-overlay {
      position: absolute;
      left: clamp(14px, 3vw, 36px);
      bottom: clamp(14px, 3vw, 34px);
      margin: 0;
      font-family: 'Manrope', sans-serif;
      font-size: clamp(68px, 16vw, 200px);
      line-height: 0.8;
      text-transform: uppercase;
      letter-spacing: -0.06em;
      color: #fff;
      mix-blend-mode: normal;
      text-shadow: 0 2px 8px rgba(0, 0, 0, 0.52);
      font-weight: 800;
      -webkit-text-fill-color: #fff;
      opacity: 1;
      z-index: 3;
      pointer-events: none;
    }

    .hero-title-overlay span {
      display: block;
      transform: translateX(0);
    }

    .hero-side {
      position: relative;
      border: 1px solid var(--line);
      background: #0f0f0f;
      min-height: 0;
      height: clamp(420px, 52vw, 760px);
      overflow: hidden;
    }

    .hero-side::before,
    .hero-side::after {
      content: '';
      position: absolute;
      left: 0;
      right: 0;
      height: 44px;
      pointer-events: none;
      z-index: 6;
    }

    .hero-side::before {
      top: 0;
      background: linear-gradient(to bottom, rgba(12, 12, 12, 0.86), rgba(12, 12, 12, 0));
    }

    .hero-side::after {
      bottom: 0;
      background: linear-gradient(to top, rgba(12, 12, 12, 0.9), rgba(12, 12, 12, 0));
    }

    .hero-side-viewport {
      height: 100%;
      overflow: auto;
      scrollbar-width: none;
      -ms-overflow-style: none;
      position: relative;
      z-index: 2;
    }

    .hero-side-viewport::-webkit-scrollbar {
      display: none;
    }

    .hero-side-track {
      display: grid;
      gap: 10px;
      padding: 10px;
    }

    .hero-card {
      border: 1px solid var(--line);
      background: #0f0f0f;
      min-height: 180px;
      display: block;
      color: inherit;
      text-decoration: none;
      position: relative;
      overflow: hidden;
      transition: transform 0.25s ease, border-color 0.25s ease, box-shadow 0.25s ease;
    }

    .hero-card img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      filter: grayscale(18%);
      display: block;
      transition: transform 0.35s ease, filter 0.35s ease;
    }

    .hero-card:hover {
      border-color: #f0f0f0;
      transform: translateY(-2px);
      box-shadow: 0 12px 28px rgba(0, 0, 0, 0.38);
    }

    .hero-card:hover img {
      transform: scale(1.035);
      filter: grayscale(6%);
    }

    .hero-card:focus-visible {
      outline: 1px solid #f0f0f0;
      outline-offset: -1px;
      border-color: #f0f0f0;
    }

    .hero-card-meta {
      position: absolute;
      left: 10px;
      right: 10px;
      bottom: 10px;
      border: 1px solid #2f2f2f;
      background: rgba(0, 0, 0, 0.76);
      color: #f3f3f3;
      padding: 7px 8px;
      display: grid;
      gap: 4px;
      backdrop-filter: blur(1.6px);
    }

    .hero-card-artist {
      margin: 0;
      font-family: 'Space Mono', monospace;
      font-size: 9px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: #d8ff5a;
    }

    .hero-card-title {
      margin: 0;
      font-family: 'Manrope', sans-serif;
      font-size: 12px;
      line-height: 1.25;
      color: #f5f5f5;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .hero-card-match {
      margin: 0;
      font-family: 'Space Mono', monospace;
      font-size: 9px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: #d0d0d0;
    }

    .hero-empty {
      position: absolute;
      left: 12px;
      bottom: 12px;
      border: 1px solid #313131;
      background: rgba(0, 0, 0, 0.72);
      padding: 6px 8px;
      color: #ececec;
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }

    .hero-stats {
      margin-top: 8px;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
    }

    .stat-card {
      border: 1px solid var(--line);
      background: #0f0f0f;
      padding: 10px;
      min-height: 72px;
    }

    .stat-card.accent {
      background: var(--lime);
      color: #090909;
      border-color: #bddd45;
    }

    .stat-label {
      margin: 0 0 6px;
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.09em;
      text-transform: uppercase;
      color: inherit;
      opacity: 0.85;
    }

    .stat-value {
      margin: 0;
      font-family: 'Manrope', sans-serif;
      font-size: clamp(20px, 2.6vw, 36px);
      line-height: 0.92;
      letter-spacing: -0.03em;
      font-weight: 700;
      color: inherit;
    }

    .marquee {
      margin-top: 8px;
      border: 1px solid var(--line);
      background: #0d0d0d;
      overflow: hidden;
      white-space: nowrap;
    }

    .marquee-track {
      display: inline-flex;
      gap: 18px;
      padding: 7px 0;
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #cbcbcb;
      animation: ticker 42s linear infinite;
    }

    @media (min-width: 1321px) {
      .hero-visual {
        height: clamp(280px, 38vh, 420px);
      }
    }

    @keyframes ticker {
      0% { transform: translateX(0); }
      100% { transform: translateX(-50%); }
    }

    .atlas-layout {
      display: grid;
      grid-template-columns: minmax(240px, 0.55fr) minmax(620px, 1.45fr);
      gap: 12px;
      align-items: stretch;
      height: auto;
    }

    .artist-stack {
      border: 1px solid var(--line);
      background: #101010;
      padding: 10px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      min-height: 682px;
      height: 100%;
      max-height: none;
      overflow: hidden;
    }

    .artist-grid {
      --artist-card-height: 160px;
      --artist-card-overlap: 114px;
      --artist-card-step: calc(var(--artist-card-height) - var(--artist-card-overlap));
      --artist-cards-visible: 5;
      display: flex;
      flex-direction: column;
      flex: 1 1 0;
      min-height: 0;
      height: auto;
      max-height: none;
      overflow: auto;
      overscroll-behavior: contain;
      padding: 2px 10px calc((var(--artist-cards-visible) - 1) * var(--artist-card-step)) 2px;
      scroll-snap-type: y proximity;
    }

    .artist-card {
      border: 1px solid var(--line);
      background: #0f0f0f;
      height: var(--artist-card-height);
      margin-top: calc(-1 * var(--artist-card-overlap));
      flex: 0 0 auto;
      overflow: hidden;
      position: relative;
      cursor: pointer;
      transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
      will-change: transform;
      scroll-snap-align: start;
    }

    .artist-card:first-child {
      margin-top: 0;
    }

    .artist-card,
    .artist-grid:hover .artist-card,
    .artist-card:hover,
    .artist-card.hover-latched {
      opacity: 1 !important;
    }

    .artist-grid:hover .artist-card {
      opacity: 1;
    }

    /* Touch: hover-latched shows border/shadow indicator, no slide transform */
    .artist-card.hover-latched {
      border-color: #fff;
      opacity: 1;
      z-index: 400 !important;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
    }

    /* Desktop with true hover: :hover and hover-latched both get the full slide */
    @media (hover: hover) and (pointer: fine) {
      .artist-card:hover,
      .artist-card.hover-latched {
        transform: translateY(12px);
        border-color: #fff;
        opacity: 1;
        z-index: 400 !important;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
      }
    }

    .artist-card.focus {
      border-color: var(--lime);
      outline: 2px solid var(--lime);
      outline-offset: -2px;
    }

    .artist-card.selected {
      border-color: var(--lime);
      box-shadow: inset 0 0 0 1px var(--lime);
    }

    @media (hover: hover) and (pointer: fine) {
      .artist-grid.selected-dock .artist-card.selected {
        transform: none;
        box-shadow: inset 0 0 0 1px var(--lime);
      }
    }

    .artist-card img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
      filter: grayscale(14%);
    }

    .artist-detail {
      position: absolute;
      left: 8px;
      right: 8px;
      bottom: 8px;
      background: rgba(38, 38, 38, 0.82);
      border: 1px solid #585858;
      padding: 8px;
      display: grid;
      gap: 4px;
      opacity: 1;
      transform: none;
      transition: border-color 0.2s ease, background 0.2s ease;
      pointer-events: auto;
      backdrop-filter: blur(1.4px);
    }

    .artist-card.hover-latched .artist-detail {
      border-color: #d0d0d0;
      background: rgba(46, 46, 46, 0.86);
    }

    @media (hover: hover) and (pointer: fine) {
      .artist-card:hover .artist-detail {
        border-color: #d0d0d0;
        background: rgba(46, 46, 46, 0.86);
      }
    }

    .artist-card.selected .artist-detail {
      border-color: var(--lime);
    }

    .artist-detail h3 {
      margin: 0;
      font-family: 'Manrope', sans-serif;
      font-size: 20px;
      line-height: 0.92;
      letter-spacing: -0.02em;
      text-transform: uppercase;
      color: #fff;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .artist-detail p {
      margin: 0;
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: #d3d3d3;
      white-space: nowrap;
    }

    .artist-meta-row {
      display: flex;
      align-items: center;
      justify-content: flex-start;
      gap: 6px;
      min-width: 0;
    }

	    .artist-card .card-actions {
	      align-items: center;
	      display: flex;
	      justify-content: flex-start;
	      gap: 4px;
	      flex: 0 0 auto;
	      flex-wrap: nowrap;
	    }

	    .artist-card .atlas-card-actions {
	      flex: 1 1 auto;
	      width: 100%;
	    }

	    .card-actions-main {
	      align-items: center;
	      display: inline-flex;
	      gap: 4px;
	    }

	    .card-actions-main {
	      flex: 1 1 auto;
	      flex-wrap: wrap;
	      min-width: 0;
	    }

	    .artist-card .card-actions .chip-btn {
	      display: inline-flex;
	      align-items: center;
      justify-content: center;
      white-space: nowrap;
      font-size: 9px;
      min-height: 22px;
      padding: 0 8px;
	      line-height: 1;
	    }

    .artist-card .card-actions .chip-btn.active {
      border-color: var(--line);
      color: #f1f1f1;
    }

    .chip-btn {
      border: 1px solid var(--line);
      background: #171717;
      color: #f1f1f1;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 10px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      min-height: 28px;
      padding: 0 8px;
      border-radius: 4px;
      font-family: 'Space Mono', monospace;
      line-height: 1;
      cursor: pointer;
      transition: border-color 120ms ease, color 120ms ease, background 120ms ease;
    }

    .chip-btn:hover { border-color: var(--lime); color: var(--lime); }
    .chip-btn.active { border-color: var(--violet); color: var(--violet); }
    .chip-btn.lime { border-color: var(--lime); color: var(--lime); }

    .atlas-panel {
      border: 1px solid var(--line);
      background: var(--paper-2);
      padding: 12px;
      display: grid;
      gap: 10px;
      align-content: start;
      min-height: 0;
      height: auto;
      overflow: visible;
    }

    .focus-header {
      border: 1px solid var(--line);
      background: #101010;
      padding: 10px;
      display: grid;
      gap: 8px;
    }

    .focus-names {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: flex-end;
    }

    .focus-names.single {
      display: block;
    }

    .focus-names.single .focus-name {
      display: inline-flex;
      align-items: center;
      margin: 0;
      font-family: 'Manrope', sans-serif;
      font-size: clamp(28px, 4vw, 62px);
      line-height: 0.85;
      letter-spacing: -0.04em;
      text-transform: uppercase;
      color: #fff;
      border: none;
      background: transparent;
      padding: 0;
    }

    .focus-names.multi {
      font-family: 'Manrope', sans-serif;
      font-size: clamp(28px, 3.4vw, 56px);
      line-height: 0.86;
      letter-spacing: -0.04em;
      text-transform: uppercase;
    }

    .focus-names.multi .focus-name {
      display: inline-flex;
      align-items: flex-start;
      gap: 4px;
      margin: 0;
      font-size: 1em;
      line-height: inherit;
      letter-spacing: inherit;
      text-transform: inherit;
      color: #fff;
      border: none;
      background: transparent;
      padding: 0;
    }

    .focus-sep {
      font-size: 1em;
      line-height: inherit;
      letter-spacing: inherit;
      color: #bdbdbd;
      margin: 0 2px;
      user-select: none;
    }

    .focus-names.multi.compact {
      font-size: clamp(20px, 2.5vw, 38px);
    }

    .focus-remove {
      border: 1px solid #333333;
      background: rgba(18, 18, 18, 0.75);
      color: #8a8a8a;
      width: 14px;
      height: 14px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-family: 'Space Mono', monospace;
      font-size: 9px;
      line-height: 1;
      padding: 0;
      margin-top: 5px;
      cursor: pointer;
      text-transform: uppercase;
      opacity: 0.96;
    }

    .focus-remove:hover {
      color: #d2d2d2;
      border-color: #5a5a5a;
      opacity: 1;
    }

    .focus-toolbar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }

    .focus-mode {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    .focus-mode .chip-btn {
      min-height: 26px;
    }

    .focus-summary {
      margin: 0;
      font-size: 12px;
      color: #bbbbbb;
      line-height: 1.45;
    }

    .focus-stats {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
    }

    .focus-tile {
      border: 1px solid var(--line);
      background: #0f0f0f;
      padding: 8px;
    }

    .focus-tile p {
      margin: 0 0 6px;
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: #bdbdbd;
    }

    .focus-tile h4 {
      margin: 0;
      font-family: 'Manrope', sans-serif;
      font-size: 18px;
      line-height: 1;
      letter-spacing: -0.02em;
    }

    .taxonomy-panel,
    .evidence-panel,
    .network-panel,
    .pair-panel,
    .set-panel {
      border: 1px solid var(--line);
      background: #101010;
      padding: 10px;
    }

    .taxonomy-workbench {
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
      align-items: start;
    }

    .evidence-panel {
      display: none;
    }

    .evidence-panel.open {
      display: block;
    }

    .panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 8px;
    }

    .panel-title {
      margin: 0;
      font-family: 'Manrope', sans-serif;
      font-size: 18px;
      text-transform: uppercase;
      letter-spacing: -0.01em;
    }

    .panel-copy {
      margin: 0;
      font-size: 12px;
      color: #bababa;
      line-height: 1.45;
    }

    .selected-chips,
    .lens-tabs,
    .pill-row,
    .row-meta,
    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    .chip {
      border: 1px solid var(--line);
      background: #161616;
      color: #e4e4e4;
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: 4px 7px;
    }

    .controls-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin-top: 8px;
    }

    .controls-grid.set-library-controls {
      grid-template-columns: minmax(0, 1fr) minmax(170px, 220px) minmax(150px, 180px);
      align-items: end;
    }

    .taxonomy-controls-bar {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: nowrap;
      overflow-x: auto;
      overflow-y: hidden;
      margin-top: 6px;
      padding-bottom: 4px;
      margin-bottom: 6px;
      border-bottom: 1px solid #2a2a2a;
    }

    .taxonomy-head {
      flex-wrap: nowrap;
      overflow-x: auto;
      overflow-y: hidden;
      padding-bottom: 2px;
    }

    .taxonomy-head .panel-title {
      flex: 0 0 auto;
    }

    .taxonomy-head .lens-tabs {
      flex: 1 1 auto;
      flex-wrap: nowrap;
      justify-content: flex-end;
    }

    .taxonomy-head .chip-btn,
    .taxonomy-controls-bar .chip-btn,
    .threshold-stepper .threshold-arrow,
    .threshold-stepper .threshold-value {
      white-space: nowrap;
      flex: 0 0 auto;
      min-height: 28px;
      padding: 0 8px;
      font-size: 10px;
      border-radius: 4px;
    }

    .taxonomy-controls-bar .taxonomy-fine-btn,
    .taxonomy-controls-bar .threshold-stepper .taxonomy-fine-btn {
      height: 25px;
      min-height: 25px;
      padding: 0 7px;
      font-size: 9px;
      letter-spacing: 0.05em;
      border-radius: 4px;
    }

    .taxonomy-controls-bar .pill-row {
      flex-wrap: nowrap;
      flex: 0 0 auto;
      gap: 4px;
    }

    .threshold-stepper {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      flex: 0 0 auto;
    }

    .threshold-stepper .threshold-arrow {
      width: 28px;
      min-width: 28px;
      padding: 0;
      text-align: center;
      font-size: 10px;
      line-height: 1;
    }

    .threshold-stepper .threshold-value {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 92px;
      border-color: #3a3a3a;
      color: #f0f0f0;
      pointer-events: none;
      cursor: default;
    }

    .threshold-stepper .threshold-arrow:disabled {
      opacity: 0.35;
      cursor: not-allowed;
    }

    .taxonomy-controls-row {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: nowrap;
      margin-left: auto;
      flex: 0 0 auto;
      min-width: 0;
    }

    .taxonomy-search-control {
      flex: 0 0 clamp(170px, 24vw, 260px);
      min-width: 0;
    }

    .taxonomy-controls-row .control {
      min-width: 0;
      display: flex;
      align-items: center;
      gap: 4px;
      flex: 0 0 clamp(120px, 16vw, 170px);
    }

    .taxonomy-controls-bar .control input,
    .taxonomy-controls-bar .control select {
      height: 25px;
      min-height: 25px;
      padding: 0 7px;
      font-size: 10px;
      line-height: 25px;
      border-radius: 4px;
    }

    .taxonomy-controls-row input,
    .taxonomy-controls-row select {
      height: 25px;
      min-height: 25px;
      padding: 0 7px;
      font-size: 10px;
      line-height: 25px;
      border-radius: 4px;
    }

    .taxonomy-controls-bar .taxonomy-field,
    .taxonomy-controls-row .taxonomy-field {
      border: 1px solid var(--line);
      background: #171717;
      color: #f0f0f0;
      font-family: 'Space Mono', monospace;
      appearance: none;
      -webkit-appearance: none;
    }

    .taxonomy-controls-bar .taxonomy-field::placeholder,
    .taxonomy-controls-row .taxonomy-field::placeholder {
      color: #838383;
      opacity: 1;
    }

    .taxonomy-controls-bar .taxonomy-field:focus,
    .taxonomy-controls-row .taxonomy-field:focus {
      outline: none;
      border-color: var(--lime);
      box-shadow: 0 0 0 1px var(--lime);
    }

    .taxonomy-controls-bar .taxonomy-fine-field::placeholder,
    .taxonomy-controls-row .taxonomy-fine-field::placeholder {
      font-size: 10px;
    }

    .taxonomy-controls-bar .taxonomy-select-field,
    .taxonomy-controls-bar .taxonomy-select-field option,
    .taxonomy-controls-row .taxonomy-select-field,
    .taxonomy-controls-row .taxonomy-select-field option {
      text-transform: uppercase;
    }

    .taxonomy-sort-icon {
      color: #c6c6c6;
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      line-height: 1;
      flex: 0 0 auto;
      user-select: none;
    }

    .control {
      display: grid;
      gap: 5px;
    }

    .control label {
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.07em;
      text-transform: uppercase;
      color: #c3c3c3;
    }

    .control input,
    .control select {
      border: 1px solid var(--line);
      background: #171717;
      color: #f0f0f0;
      height: 26px;
      min-height: 26px;
      padding: 0 7px;
      font-size: 10px;
      border-radius: 8px;
      width: 100%;
      font-family: 'Space Mono', monospace;
    }

    .controls-grid.set-library-controls select,
    .controls-grid.set-library-controls select option {
      text-transform: uppercase;
    }

    .control input:focus,
    .control select:focus {
      outline: none;
      border-color: var(--lime);
      box-shadow: 0 0 0 1px var(--lime);
    }

    .rows {
      display: grid;
      gap: 6px;
      max-height: none;
      overflow: visible;
      padding-right: 0;
    }

    .quant-row {
      border: 1px solid var(--line);
      background: #131313;
      padding: 5px 7px;
      display: grid;
      gap: 4px;
      cursor: default;
    }

    .quant-row:hover { border-color: #f0f0f0; }
    .quant-row.active { border-color: var(--lime); }

    .row-hit {
      border: 0;
      background: transparent;
      padding: 0;
      margin: 0;
      width: 100%;
      text-align: left;
      color: inherit;
      display: block;
      cursor: pointer;
      font: inherit;
    }

    .row-line {
      display: grid;
      grid-template-columns: clamp(120px, 16vw, 180px) minmax(0, 1fr) auto;
      align-items: center;
      gap: 6px;
    }

    .row-name {
      font-family: 'Manrope', sans-serif;
      font-size: 13px;
      line-height: 1.1;
      color: #fff;
      min-width: 0;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .row-count {
      font-family: 'Space Mono', monospace;
      font-size: 11px;
      color: #cfcfcf;
      letter-spacing: 0.05em;
    }

    .bar {
      height: 6px;
      border: 1px solid #2e2e2e;
      background: #0d0d0d;
      position: relative;
      overflow: hidden;
    }

    .bar > span {
      position: absolute;
      inset: 0 auto 0 0;
      background: var(--lime);
      width: 0;
    }

    .inline-evidence {
      margin-top: 8px;
      border-top: 1px solid #2f3b1a;
      padding-top: 8px;
      display: grid;
      gap: 8px;
      background: #0f1210;
      border: 1px solid #273122;
      padding: 8px;
    }

    .inline-evidence .evidence-grid {
      grid-auto-columns: calc((100% - 24px) / 5);
      gap: 6px;
    }

    .inline-evidence .track-body {
      padding: 6px;
      gap: 5px;
    }

    .inline-evidence .track-title {
      font-size: 12px;
      line-height: 1.2;
    }

    .inline-evidence .muted {
      font-size: 10px;
      line-height: 1.35;
    }

    .inline-evidence .chip {
      font-size: 9px;
      padding: 2px 4px;
    }

    .inline-evidence .actions {
      gap: 4px;
    }

    .inline-evidence .actions a,
    .inline-evidence .actions button {
      font-size: 9px;
      padding: 3px 5px;
    }

    .inline-evidence .inline-head {
      margin: 0;
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: #bfc5b2;
    }

    .inline-evidence .inline-head-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
      flex-wrap: wrap;
    }

    .inline-evidence .inline-head-actions {
      display: flex;
      align-items: center;
      gap: 4px;
    }

    .inline-evidence .inline-head-actions a {
      border: 1px solid var(--line);
      background: #171717;
      color: #f0f0f0;
      font-family: 'Space Mono', monospace;
      font-size: 9px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: 3px 5px;
      text-decoration: none;
    }

    .inline-evidence .inline-head-actions a:hover {
      border-color: #fff;
    }

    .inline-evidence .inline-head-actions a.discogs {
      border-color: #7db8f2;
      color: #7db8f2;
    }

    .pager {
      margin-top: 8px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
    }

    .pager .info {
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      color: #bdbdbd;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }

    .pager button,
    .small-btn,
    .text-btn {
      border: 1px solid var(--line);
      background: #171717;
      color: #ececec;
      height: 30px;
      padding: 0 10px;
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      cursor: pointer;
    }

    .pager button:hover,
    .small-btn:hover,
    .text-btn:hover { border-color: #fff; }

    .evidence-grid {
      display: grid;
      grid-auto-flow: column;
      grid-auto-columns: minmax(260px, 330px);
      overflow-x: auto;
      overflow-y: visible;
      padding-bottom: 6px;
      gap: 10px;
    }

    .pair-track-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }

    .set-grid {
      column-count: 4;
      column-gap: 10px;
    }

    .track-card,
    .pair-track-card,
    .set-card {
      border: 1px solid var(--line);
      background: #0f0f0f;
      overflow: hidden;
    }

    .set-card {
      display: inline-block;
      width: 100%;
      margin: 0 0 10px;
      break-inside: avoid;
      vertical-align: top;
      position: relative;
      overflow: visible;
    }

    .track-art,
    .set-thumb {
      aspect-ratio: 1 / 1;
      border-bottom: 1px solid var(--line);
      background: #141414;
      position: relative;
      overflow: hidden;
    }

    .track-art img,
    .set-thumb img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
      filter: grayscale(18%);
    }

    .set-title a,
    .set-thumb a {
      color: inherit;
      text-decoration: none;
    }

    .set-thumb a {
      display: block;
      width: 100%;
      height: 100%;
    }

    .set-title a {
      border-bottom: 1px solid transparent;
    }

    .set-title a:hover {
      border-color: var(--lime);
    }

    .track-body,
    .set-body,
    .pair-track-body {
      padding: 10px;
      display: grid;
      gap: 8px;
    }

    .track-card .track-body {
      position: relative;
    }

    .track-title,
    .set-title,
    .pair-track-title {
      margin: 0;
      font-family: 'Manrope', sans-serif;
      font-size: 16px;
      line-height: 1.25;
      color: #fff;
    }

    .muted {
      margin: 0;
      color: #bdbdbd;
      font-size: 12px;
      line-height: 1.45;
    }

    .muted a {
      color: #d8d8d8;
      text-decoration: underline;
      text-decoration-color: #323232;
      text-underline-offset: 2px;
    }

    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
    }

    .actions a,
    .actions button {
      border: 1px solid var(--line);
      background: #171717;
      color: #f0f0f0;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      min-height: 24px;
      padding: 0 6px;
      border-radius: 4px;
      line-height: 1;
      font-size: 9px;
      letter-spacing: 0.06em;
      cursor: pointer;
      text-decoration: none;
      transition: border-color 120ms ease, color 120ms ease, background 120ms ease;
    }

    .actions a:hover,
    .actions button:hover { border-color: var(--lime); color: var(--lime); }

    .actions .spotify {
      border-color: #1db954;
      color: #1db954;
    }

    .source-panel {
      border-top: 1px solid var(--line);
      margin-top: 8px;
      padding-top: 8px;
      display: none;
      gap: 8px;
    }

    .source-panel.open { display: grid; }

    .source-group {
      border: 1px solid var(--line);
      background: #151515;
      padding: 8px;
      display: grid;
      gap: 6px;
    }

    .source-group h5 {
      margin: 0;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: #d8d8d8;
      font-family: 'Space Mono', monospace;
    }

    .source-group h5 a {
      color: inherit;
      text-decoration: underline;
      text-decoration-color: #343434;
      text-underline-offset: 2px;
    }

    .source-list {
      margin: 0;
      padding-left: 18px;
      display: grid;
      gap: 4px;
    }

    .source-list li {
      color: #d8d8d8;
      font-size: 12px;
      line-height: 1.35;
    }

    .source-list li::marker {
      color: var(--lime);
    }

    .source-list a {
      color: #efefef;
      text-decoration: underline;
      text-decoration-color: #343434;
      text-underline-offset: 2px;
    }

    .source-empty {
      margin: 0;
      color: #a9a9a9;
      font-size: 12px;
    }

    .spotify-embed {
      grid-column: 1 / -1;
      margin-top: 8px;
      border: 0;
      background: transparent;
      padding: 0;
    }

    .spotify-embed iframe {
      border: 0;
      width: 100%;
      height: 160px;
      border-radius: 14px;
    }

    .evidence-grid .track-card.embed-open,
    .inline-evidence .track-card.embed-open,
    .evidence-grid .track-card.sources-open,
    .inline-evidence .track-card.sources-open {
      width: calc(200% + 10px);
      height: var(--open-card-height, auto);
      overflow: hidden;
      z-index: 40;
    }

    .track-card.embed-open .track-art,
    .track-card.sources-open .track-art {
      aspect-ratio: auto;
      height: var(--open-art-height, 260px);
    }

    .track-card.embed-open .track-body {
      height: var(--open-body-height, auto);
      padding: 0;
      overflow: hidden;
      display: grid;
      grid-template-rows: minmax(var(--open-action-row-height, 36px), auto) var(--open-embed-height, 91.2px);
      gap: 0;
      align-content: start;
    }

    .track-card.sources-open .track-body {
      height: var(--open-body-height, auto);
      padding: 0;
      overflow: hidden;
      display: grid;
      grid-template-rows: minmax(var(--open-action-row-height, 36px), auto) var(--open-source-height, 91.2px);
      gap: 0;
      align-content: start;
    }

    .track-card.embed-open .track-body > .track-title,
    .track-card.embed-open .track-body > .muted,
    .track-card.embed-open .track-body > .source-panel {
      display: none;
    }

    .track-card.sources-open .track-body > .track-title,
    .track-card.sources-open .track-body > .muted {
      display: none;
    }

    .track-card.embed-open .track-body > .actions,
    .track-card.sources-open .track-body > .actions {
      margin: 0;
      min-height: var(--open-action-row-height, 36px);
      padding: 8px 6px 4px;
      border-bottom: 1px solid var(--line);
      background: #0f0f0f;
      gap: 6px;
      align-items: center;
      flex-wrap: nowrap;
      overflow-x: auto;
      overflow-y: hidden;
      box-sizing: border-box;
      z-index: 3;
    }

    .track-card .track-body .spotify-embed {
      display: none;
      margin: 0;
      height: 100%;
      position: relative;
      overflow: hidden;
    }

    .track-card.embed-open .track-body .spotify-embed {
      display: block;
      padding: 0;
      width: 100%;
      height: var(--open-embed-height, 91.2px);
      display: flex;
      align-items: flex-start;
    }

    .track-card.sources-open .track-body .source-panel {
      display: none;
    }

    .track-card.sources-open .track-body .source-panel.open {
      display: grid;
      margin: 0;
      padding: 6px;
      border-top: 0;
      width: 100%;
      height: var(--open-source-height, 91.2px);
      overflow-y: auto;
      overflow-x: hidden;
      gap: 6px;
      align-content: start;
      box-sizing: border-box;
    }

    .evidence-grid .track-card.embed-open:nth-child(even),
    .inline-evidence .track-card.embed-open:nth-child(even),
    .evidence-grid .track-card.sources-open:nth-child(even),
    .inline-evidence .track-card.sources-open:nth-child(even) {
      margin-left: calc(-100% - 10px);
    }

    .track-card.embed-open .track-body .spotify-embed iframe {
      width: 100%;
      height: var(--open-embed-height, 91.2px);
      display: block;
      margin: 0;
      border-radius: 0;
    }

    .pair-track-card.embed-open .spotify-embed iframe {
      height: 196px;
    }

    .network-wrap {
      border: 1px solid var(--line);
      background: #0f0f0f;
      min-height: 560px;
      position: relative;
      overflow: hidden;
    }

    .network-svg {
      width: 100%;
      height: 560px;
      display: block;
    }

    .network-node {
      cursor: pointer;
      transition: r 0.2s ease;
    }

    .network-node:hover { r: 14; }
    .network-node.focus { stroke: var(--lime); stroke-width: 3; }
    .network-node.selected { stroke: var(--violet); stroke-width: 3; }

    .network-controls {
      display: flex;
      align-items: flex-end;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 0;
      margin-bottom: 10px;
    }

    .network-controls .control {
      flex: 0 1 clamp(180px, 24vw, 320px);
      min-width: 0;
    }

    .network-controls .control input,
    .network-controls .control select {
      height: 28px;
      min-height: 28px;
      padding: 0 8px;
      font-size: 10px;
    }

    .network-controls .network-clear-wrap {
      margin-left: auto;
      flex: 0 0 auto;
    }

    .pair-grid {
      display: grid;
      gap: 8px;
    }

    .pair-rows {
      display: grid;
      gap: 6px;
      max-height: none;
      overflow: visible;
      padding-right: 0;
    }

    .pair-row {
      border: 1px solid var(--line);
      background: #131313;
      padding: 5px 7px;
      display: grid;
      gap: 4px;
      cursor: pointer;
    }

    .pair-row:hover { border-color: #fff; }
    .pair-row.active { border-color: var(--lime); }

    .set-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
    }

    .set-pill {
      border: 1px solid #2c2c2c;
      background: #171717;
      color: #dcdcdc;
      font-size: 10px;
      font-family: 'Space Mono', monospace;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: 4px 6px;
    }

    .set-tracklist {
      position: absolute;
      left: 0;
      width: 100%;
      top: 100%;
      border: 1px solid var(--line);
      background: #101010;
      box-shadow: 0 18px 36px rgba(0, 0, 0, 0.45);
      padding: 10px;
      display: none;
      gap: 6px;
      max-height: 260px;
      overflow: auto;
      padding-right: 2px;
      z-index: 40;
      box-sizing: border-box;
    }

    .set-tracklist.open { display: grid; }

    .set-track {
      border: 1px solid var(--line);
      background: #161616;
      padding: 6px;
      display: grid;
      grid-template-columns: auto 1fr auto;
      gap: 6px;
      align-items: center;
      font-size: 12px;
    }

    .set-track-time {
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      color: #cbcbcb;
      min-width: 48px;
    }

    .set-track-conf {
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      padding: 2px 5px;
      border: 1px solid #333;
      color: #cfcfcf;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }

    .set-track-conf.high {
      border-color: #6fffa4;
      color: #6fffa4;
      background: rgb(111 255 164 / 12%);
    }

    .set-track-conf.medium {
      border-color: #ffd166;
      color: #ffd166;
      background: rgb(255 209 102 / 12%);
    }

    .set-track-conf.low {
      border-color: #ffa55a;
      color: #ffa55a;
      background: rgb(255 165 90 / 12%);
    }

    .set-track-conf.uncertain {
      border-color: #7b7b7b;
      color: #7b7b7b;
      background: rgb(123 123 123 / 12%);
    }

    .footer {
      border: 1px solid var(--line);
      background: #111;
      padding: var(--page-pad);
      margin-top: var(--page-gutter);
    }

    .footer h2 {
      margin: 0;
      font-family: 'Manrope', sans-serif;
      font-size: clamp(32px, 8vw, 120px);
      line-height: 0.88;
      letter-spacing: -0.04em;
      text-transform: uppercase;
    }

    .footer p {
      margin: 10px 0 0;
      max-width: 780px;
      font-size: 13px;
      color: #c6c6c6;
      line-height: 1.6;
    }

    .empty {
      border: 1px solid var(--line);
      background: #131313;
      color: #bcbcbc;
      padding: 12px;
      font-size: 12px;
      line-height: 1.45;
    }

    .reveal {
      opacity: 1;
      transform: none;
      transition: opacity 0.45s ease, transform 0.45s ease;
    }

    .reveal.in {
      opacity: 1;
      transform: translateY(0);
    }

    @media (max-width: 1320px) {
      .taxonomy-workbench { grid-template-columns: 1fr; }
      .pair-track-grid { grid-template-columns: 1fr; }
      .set-grid { column-count: 2; }
      .hero-grid { grid-template-columns: 1fr; }
      .hero-side {
        height: auto !important;
        min-height: clamp(280px, 58vw, 430px);
      }
      .focus-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .controls-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .controls-grid.set-library-controls { grid-template-columns: minmax(0, 1fr) minmax(180px, 220px); }
      .controls-grid.set-library-controls > .control:first-child { grid-column: 1 / -1; }
    }

    @media (max-width: 980px) {
      .section-head { grid-template-columns: 1fr; }
      .section-head p { justify-self: start; max-width: 100%; }
      .atlas-layout { grid-template-columns: 1fr; align-items: start; height: auto; }
      .artist-stack,
      .atlas-panel { height: auto; min-height: 0; }
      .artist-stack,
      .artist-grid,
      .atlas-panel {
        min-width: 0;
        width: 100%;
        max-width: 100%;
      }
      .atlas-panel { overflow: visible; }
      .artist-grid { flex: 0 0 auto; height: calc(var(--artist-card-height) + (var(--artist-cards-visible) - 1) * var(--artist-card-step)); max-height: calc(var(--artist-card-height) + (var(--artist-cards-visible) - 1) * var(--artist-card-step)); }
      .hero-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .set-grid { column-count: 2; }
    }

    @media (max-width: 680px) {
      .hero-side {
        min-height: clamp(240px, 72vw, 340px);
      }
      .artist-grid {
        --artist-card-height: 132px;
        --artist-card-overlap: 74px;
      }
      .evidence-grid {
        grid-auto-columns: minmax(240px, 82vw);
      }
      .pair-track-grid { grid-template-columns: 1fr; }
      .set-grid { column-count: 1; }
      .controls-grid { grid-template-columns: 1fr; }
      .controls-grid.set-library-controls { grid-template-columns: 1fr; }
      .controls-grid.set-library-controls > .control:first-child { grid-column: auto; }
      .focus-stats { grid-template-columns: 1fr 1fr; }
      .section-head h2 { font-size: clamp(34px, 15vw, 58px); }
      .hero-title-overlay { font-size: clamp(58px, 22vw, 120px); }
    }

    @media (max-width: 480px) {
      .topbar-right {
        flex-wrap: wrap;
        width: 100%;
      }
      .shell {
        padding-left: 10px;
        padding-right: 10px;
        overflow-x: hidden;
      }
      /* Change 6: network graph — reduce dead space; enable touch gestures */
      .network-wrap {
        min-height: 380px;
        touch-action: none;
        user-select: none;
      }
      .network-svg {
        height: 380px;
      }
      .hero-stats,
      .focus-stats {
        grid-template-columns: 1fr;
      }
      .atlas-layout {
        grid-template-columns: minmax(0, 1fr);
      }
      .artist-stack,
      .atlas-panel {
        min-width: 0;
      }
      /* Atlas panel grid items — prevent overflow down the nesting chain */
      .focus-header,
      .taxonomy-workbench,
      .taxonomy-panel,
      .evidence-panel,
      .network-panel,
      .pair-panel,
      .set-panel,
      .panel-head {
        min-width: 0;
      }
      /* Taxonomy head tabs — wrap and scroll on mobile */
      .taxonomy-head {
        flex-wrap: wrap;
      }
      .lens-tabs {
        overflow-x: auto;
        max-width: 100%;
      }
      .artist-grid {
        max-height: none;
      }
      .hero-title-overlay {
        font-size: clamp(42px, 18vw, 80px);
      }
      .section-inner {
        padding: 12px;
      }
      .section-head h2 {
        font-size: clamp(28px, 12vw, 48px);
      }
      /* Change 1: hide hero side-rail scroll wheel */
      .hero-side {
        display: none;
      }
      /* Change 2: artist atlas heading wraps around submit button */
      #artists .section-head h2 {
        padding-right: 150px;
      }
      /* Change 3: evidence track cards — wide horizontal scroll */
      .evidence-grid,
      .inline-evidence .evidence-grid {
        grid-auto-flow: column;
        grid-auto-columns: minmax(240px, 80vw);
        grid-template-columns: none;
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        padding-bottom: 8px;
      }
      /* Change 4 & 5: taxonomy controls — wrap into two rows */
      .taxonomy-controls-row {
        flex-wrap: wrap;
        margin-left: 0;
        width: 100%;
      }
      .taxonomy-search-control {
        flex: 0 0 100%;
      }
      /* Item 6: taxonomy controls bar — wrap all controls, no horizontal overflow */
      .taxonomy-controls-bar {
        flex-wrap: wrap;
        overflow: hidden;
      }
      .taxonomy-controls-bar .pill-row {
        flex-wrap: wrap;
      }
      /* Item 11: disable 200% card expansion on mobile — keep within card bounds */
      .track-card.embed-open,
      .track-card.sources-open {
        width: 100%;
        max-width: 100%;
      }
      /* Cancel even-card negative margin */
      .evidence-grid .track-card.embed-open:nth-child(even),
      .inline-evidence .track-card.embed-open:nth-child(even),
      .evidence-grid .track-card.sources-open:nth-child(even),
      .inline-evidence .track-card.sources-open:nth-child(even) {
        margin-left: 0;
      }
      /* Constrain spotify embed to card width */
      .spotify-embed,
      .spotify-inline {
        max-width: 100%;
        overflow: hidden;
        box-sizing: border-box;
      }
      .spotify-embed iframe,
      .spotify-inline iframe {
        max-width: 100%;
        width: 100% !important;
      }
    }`;
