// Onboarding picker, injected into every frame of the onboarding browser.
//  - instruction overlay (top frame only, isolated in a shadow root)
//  - inspector-style hover highlight
//  - click capture: "intercept" (record + swallow the click) or "passive" (record, let it through)
//  - job-card inference: from one clicked element, find the repeated card and its fields
// Talks to Python through two bindings: __onboardEvent(payload) and __onboardHello() → state.
(() => {
  if (window.__onboard) return;

  const HOST_ID = "__onboard-host";
  const HL_ID = "__onboard-hl";
  const isTop = window.top === window;
  const state = { step: null, mode: "off", title: "", message: "", buttons: [], preview: null, status: "",
                  popupRecording: false, popupCount: 0 };
  let paused = false;
  let collapsed = false;
  let atTop = false;

  const send = (payload) => {
    try { if (window.__onboardEvent) window.__onboardEvent(payload); } catch (e) { /* page unloading */ }
  };
  const inOverlay = (el) => !!(el && el.closest && (el.closest("#" + HOST_ID) || el.closest("#" + HL_ID)));
  const cssStr = (v) => String(v).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  const clean = (t) => String(t || "").replace(/\s+/g, " ").trim();

  // ── Stable selector building blocks ─────────────────────────────────
  const STATE_CLASS = /^(is-|has-|js-)|^(active|selected|hover|hovered|focus|focused|open|opened|visible|hidden|current|disabled|expanded|collapsed|odd|even|first|last|clicked|asc|desc|ascending|descending|sorted|sorting)$|^sort(ed)?-/i;

  function isStableClass(c) {
    if (!c || c.length > 40 || STATE_CLASS.test(c)) return false;
    if (/^(css|sc|jsx|emotion|styled|svelte|tw)-/i.test(c)) return false;            // CSS-in-JS
    if (/__[A-Za-z0-9_-]{5,}$/.test(c) && /\d/.test(c.split("__").pop())) return false; // CSS modules hash
    if (/[-_][a-f0-9]{5,}$/i.test(c) && /\d/.test(c)) return false;
    const plain = !/[-_]/.test(c);
    if (plain && /\d/.test(c) && /[A-Za-z]/.test(c) && c.length <= 12) return false;      // sMn82b, r0wTof
    if (plain && c.length <= 8 && (c.match(/[A-Z]/g) || []).length >= 3) return false;  // QJPWVe
    return true;
  }

  function isStableId(id) {
    return !!id && id.length <= 40 && !/\d{3,}/.test(id) && !/[:]/.test(id) && !/^\d/.test(id)
      && isStableClass(id.replace(/:/g, ""));
  }

  // forItem: attributes that are safe on repeated items (no per-item text like aria-label)
  function stableAttrs(el, forItem) {
    const out = [];
    for (const { name, value } of el.attributes) {
      if (name.startsWith("data-onboard")) continue;
      const itemSafe = name === "role" || name === "itemprop" || name === "type" || name.startsWith("data-");
      const singleSafe = /^(name|aria-label|placeholder|title|rel)$/.test(name);
      if (!(itemSafe || (!forItem && singleSafe))) continue;
      if (!value || value.length > 40 || /\d{3,}/.test(value) || /^[0-9a-f-]{16,}$/i.test(value)) continue;
      if (forItem && name.startsWith("data-") && (/\s/.test(value) || /\d/.test(value) || value.length > 25)) continue;
      out.push(`[${name}="${cssStr(value)}"]`);
    }
    return out.slice(0, 3);
  }

  function sig(el, forItem = true) {
    const tag = el.tagName.toLowerCase();
    const classes = [...el.classList].filter(isStableClass).slice(0, 3);
    return tag + classes.map((c) => "." + CSS.escape(c)).join("") + stableAttrs(el, forItem).join("");
  }

  // Like sig(), but keeps only classes/attributes shared with same-tag siblings (cards vary: "featured", "new")
  function sigShared(el) {
    const tag = el.tagName.toLowerCase();
    let classes = [...el.classList].filter(isStableClass);
    let attrs = stableAttrs(el, true);
    const sibs = el.parentElement ? [...el.parentElement.children].filter((s) => s !== el && s.tagName === el.tagName) : [];
    if (sibs.length >= 2) {
      const shared = (test) => sibs.filter(test).length >= sibs.length * 0.6;
      classes = classes.filter((c) => shared((s) => s.classList.contains(c)));
      attrs = attrs.filter((a) => shared((s) => { try { return s.matches(a); } catch (e) { return false; } }));
    }
    return tag + classes.slice(0, 3).map((c) => "." + CSS.escape(c)).join("") + attrs.join("");
  }

  function xpath(el) {
    const parts = [];
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      let i = 1;
      for (let s = n.previousElementSibling; s; s = s.previousElementSibling) if (s.tagName === n.tagName) i++;
      parts.unshift(`${n.tagName.toLowerCase()}[${i}]`);
    }
    return "/" + parts.join("/");
  }

  const isVisible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 && r.height <= 0) return false;
    const s = getComputedStyle(el);
    return s.visibility !== "hidden" && s.display !== "none";
  };

  function ownText(el) {
    let t = "";
    for (const n of el.childNodes) if (n.nodeType === 3) t += n.textContent;
    return clean(t);
  }

  // Icon fonts / decorative elements whose "text" is a ligature like "place" or "corporate_fare"
  const ICON = 'svg, [aria-hidden="true"], i[class*="icon"], i[class*="fa-"], [class*="material-icons"], [class*="material-symbols"]';
  function iconWithin(node, root) {
    for (let a = node; a && a !== root.parentElement; a = a.parentElement) {
      try { if (a.matches(ICON)) return a; } catch (e) { return null; }
    }
    return null;
  }

  // Visible text of el without icon ligatures (mirrors scrape/extract.js)
  function textOf(el) {
    if (!el.querySelector(ICON)) return clean(el.innerText);
    let out = "";
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      const p = n.parentElement;
      if (p && !iconWithin(p, el) && p.getClientRects().length) out += n.textContent;
    }
    return clean(out);
  }

  function textLeaves(root) {
    const out = [];
    const walk = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    for (let n = root; n; n = walk.nextNode()) {
      if (/^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|SVG)$/i.test(n.tagName) || iconWithin(n, root)) continue;
      if (ownText(n) && n.getClientRects().length) out.push(n);
    }
    return out;
  }

  const safeCount = (root, sel) => { try { return root.querySelectorAll(sel).length; } catch (e) { return -1; } };

  // Selector for `el` relative to `card` (used with card.querySelector / querySelectorAll)
  function relSel(card, el) {
    if (card === el || !el.parentElement) return null;
    const p = el.parentElement;
    return p === card ? ":scope > " + sig(el) : sig(p) + " > " + sig(el);
  }

  // "Sunnyvale, CA" + "; Atlanta, GA" + "; +5 more" as sibling spans → one field: their inline wrapper
  const INLINE = /^(SPAN|A|B|STRONG|EM|SMALL|I|LABEL|TIME|ABBR)$/;
  function promote(leaf, card) {
    const p = leaf.parentElement;
    if (p && p !== card && card.contains(p) && INLINE.test(leaf.tagName) && INLINE.test(p.tagName) && !ownText(p)
        && p.children.length <= 8 && [...p.children].every((c) => INLINE.test(c.tagName))) return p;
    return leaf;
  }

  // Exact path from card to el; :nth-of-type only where siblings look identical (classless <td>s, hashed spans)
  function pathSelector(card, el) {
    if (card === el || !card.contains(el)) return null;
    const steps = [];
    for (let n = el; n && n !== card; n = n.parentElement) {
      const parent = n.parentElement;
      if (!parent) return null;
      let s = sig(n);
      const lookalikes = [...parent.children].filter((c) => { try { return c.matches(s); } catch (e) { return false; } });
      if (lookalikes.length > 1) {
        const sameTag = [...parent.children].filter((c) => c.tagName === n.tagName);
        s += `:nth-of-type(${sameTag.indexOf(n) + 1})`;
      }
      steps.unshift(s);
    }
    return ":scope > " + steps.join(" > ");
  }

  function uniqueSelectors(el) {
    const out = [];
    const add = (s) => { if (s && !out.includes(s)) out.push(s); };
    const unique = (s) => {
      try { const all = document.querySelectorAll(s); return all.length === 1 && all[0] === el; } catch (e) { return false; }
    };
    if (isStableId(el.id) && unique("#" + CSS.escape(el.id))) add("#" + CSS.escape(el.id));
    const own = sig(el, false);
    if (unique(own)) add(own);
    let chain = own;
    let a = el.parentElement;
    for (let i = 0; a && a !== document.documentElement && i < 6; i++, a = a.parentElement) {
      chain = (isStableId(a.id) ? "#" + CSS.escape(a.id) : sig(a, false)) + " " + chain;
      if (unique(chain)) { add(chain); break; }
    }
    const text = clean(el.innerText);
    if (text && text.length <= 40 && /^(A|BUTTON|SPAN|LI|DIV|LABEL)$/.test(el.tagName)) {
      add(`${el.tagName.toLowerCase()}:text-is("${cssStr(text)}")`);  // Playwright CSS extension
    }
    const aria = el.getAttribute("aria-label");
    if (aria && aria.length <= 60) add(`${el.tagName.toLowerCase()}[aria-label="${cssStr(aria)}"]`);
    add("xpath=" + xpath(el));
    return out;
  }

  const INPUT_LIKE = 'input:not([type=checkbox]):not([type=radio]):not([type=submit]):not([type=button]):not([type=hidden]), textarea, [contenteditable="true"], [role="searchbox"], [role="combobox"]';
  const CLICKABLE = 'a, button, [role="button"], [role="link"], input[type="submit"], input[type="button"]';

  function describe(el) {
    const r = el.getBoundingClientRect();
    const attrs = {};
    for (const a of el.attributes) if (!a.name.startsWith("data-onboard")) attrs[a.name] = a.value.slice(0, 200);
    const link = el.closest("a[href]");
    const text = clean(el.innerText || el.value || "");
    return {
      tag: el.tagName.toLowerCase(),
      text: text.slice(0, 200),
      attrs,
      href: link ? link.href : null,
      rect: { x: r.x, y: r.y, width: r.width, height: r.height },
      inputLike: el.matches(INPUT_LIKE),
      value: "value" in el ? el.value : null,
      candidates: uniqueSelectors(el),
      pageTemplate: /^\d+$/.test(text) ? `${sig(el, true)}:text-is("{page}")` : null,
    };
  }

  function normalizeTarget(el, step) {
    if (!el || el.nodeType !== 1) el = el && el.parentElement;
    if (!el) return null;
    if (step === "search") return el.closest(INPUT_LIKE) || el.closest(CLICKABLE) || el;
    if (step === "next" || step === "popup") return el.closest(CLICKABLE) || el;
    return el;
  }

  // ── Job-card inference ──────────────────────────────────────────────
  const LOC_RE = /\b(remote|hybrid|on-?site|in-?office|anywhere|worldwide|india|bengaluru|bangalore|hyderabad|pune|mumbai|delhi|gurugram|gurgaon|noida|chennai|kolkata|united states|usa|u\.s\.|united kingdom|uk|london|san francisco|new york|seattle|austin|boston|chicago|los angeles|mountain view|palo alto|sunnyvale|san jose|toronto|vancouver|dublin|berlin|munich|amsterdam|paris|zurich|singapore|sydney|melbourne|tokyo|tel aviv|warsaw|madrid|barcelona|lisbon|stockholm|canada|germany|ireland|france|japan|australia|netherlands|spain|poland|israel|brazil|mexico|emea|apac|americas)\b|,\s*[A-Z]{2}\b/i;
  const DATE_RE = /\b(\d+\+?\s*(minute|hour|day|week|month|year)s?\s+ago|today|yesterday|just posted|posted|\d{4}-\d{2}-\d{2}|\d{1,2}\/\d{1,2}\/\d{2,4}|(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(,\s*\d{4})?)\b/i;
  const DEPT_RE = /\b(engineering|software|product|design|data|research|science|machine learning|ai|infrastructure|platform|security|it|sales|marketing|finance|legal|operations|people|hr|human resources|recruiting|support|customer|success|business|analytics|hardware|devops|sre|mobile|quality|qa|program|communications|g&a)\b/i;

  const linkOf = (m) => m.closest("a[href]") || m.querySelector("a[href]");
  const hasNesting = (members) => members.some((m) => members.some((o) => o !== m && m.contains(o)));

  function biggestTextLeaf(card) {
    let best = null, bestScore = -1;
    for (const leaf of textLeaves(card)) {
      const s = getComputedStyle(leaf);
      const score = parseFloat(s.fontSize) * (parseInt(s.fontWeight, 10) >= 600 ? 1.3 : 1);
      if (score > bestScore) { best = leaf; bestScore = score; }
    }
    return best;
  }

  function fieldSelectors(card, el, members, needText) {
    const out = [];
    const sample = members.slice(0, 40);
    const consistent = (s) => {
      let hits = 0;
      for (const m of sample) {
        let e = null;
        try { e = m.querySelector(s); } catch (x) { return false; }
        if (e && (!needText || textOf(e))) hits++;
      }
      return hits >= sample.length * 0.6;
    };
    // a candidate must select exactly this element in the picked card
    const add = (s, mustBeConsistent) => {
      if (!s || out.includes(s)) return;
      try { if (card.querySelector(s) !== el) return; } catch (e) { return; }
      if (mustBeConsistent && !consistent(s)) return;
      out.push(s);
    };
    add(sig(el), true);                 // short & readable, when it isn't ambiguous
    add(relSel(card, el), true);
    add(pathSelector(card, el), false); // exact position: always right for the picked card
    return out;
  }

  function idAttribute(card, members) {
    const nodes = [card, ...card.querySelectorAll("*")].slice(0, 120);
    const sample = members.slice(0, 30);
    let best = null;
    for (const node of nodes) {
      for (const at of node.attributes) {
        if (/^(class|style|href|src|srcset|alt|title|aria-.*|data-onboard.*)$/.test(at.name)) continue;
        if (!/^[\w.:-]{2,80}$/.test(at.value) || !/\d/.test(at.value)) continue;
        const sel = node === card ? null : relSel(card, node);
        const vals = sample.map((m) => { const n = sel ? m.querySelector(sel) : m; return n ? n.getAttribute(at.name) : null; }).filter(Boolean);
        if (vals.length < sample.length * 0.8 || new Set(vals).size !== vals.length) continue;
        const score = (/id|req|job|posting/i.test(at.name) ? 2 : 0) + (node === card ? 1 : 0);
        if (!best || score > best.score) best = { score, spec: { selectors: sel ? [sel] : [], attr: at.name } };
      }
    }
    return best ? best.spec : null;
  }

  function cardAttributes(card) {
    const out = [];
    for (const node of [card, ...card.querySelectorAll("*")].slice(0, 150)) {
      for (const at of node.attributes) {
        if (/^(class|style|src|srcset|data-onboard.*)$/.test(at.name) || !at.value || at.value.length > 300) continue;
        out.push({ selectors: node === card ? [] : [relSel(card, node)].filter(Boolean), attr: at.name, value: at.value });
      }
    }
    return out;
  }

  function inferCard(target) {
    let el = target;
    while (el && el !== document.body && !clean(el.innerText)) el = el.parentElement;  // clicked an icon
    if (!el || el === document.body) return null;

    const levels = [];
    let a = el;
    for (let depth = 0; a && a.parentElement && a !== document.body && depth < 15; depth++, a = a.parentElement) {
      const groupSel = sig(a.parentElement) + " > " + sigShared(a);
      let members;
      try { members = [...document.querySelectorAll(groupSel)].filter(isVisible); } catch (e) { continue; }
      if (members.length < 2 || members.length > 1000 || !members.includes(a) || hasNesting(members)) continue;
      const rs = relSel(a, el);
      const k0 = rs ? safeCount(a, rs) : 1;
      if (k0 < 1 || k0 > 3) continue;   // a card holds one title, not a whole list of them
      const leaves0 = textLeaves(a).length;
      const link0 = !!linkOf(a);
      let good = 0, similar = 0;
      for (const m of members) {
        if ((rs ? safeCount(m, rs) : 1) === k0) good++;
        const lc = textLeaves(m).length;
        if (Math.abs(lc - leaves0) <= Math.max(1, leaves0 * 0.5) && !!linkOf(m) === link0) similar++;
      }
      levels.push({ el: a, depth, groupSel, members, frac: good / members.length, sim: similar / members.length });
    }
    const ok = levels.filter((l) => l.frac >= 0.8 && l.sim >= 0.6);
    if (!ok.length) return null;
    const maxN = Math.max(...ok.map((l) => l.members.length));
    // most inclusive level that still has (almost) as many members as the largest group
    const best = ok.filter((l) => l.members.length >= 0.9 * maxN).sort((x, y) => y.depth - x.depth)[0];
    const card = best.el, members = best.members;

    const candidates = [best.groupSel];
    const loose = sigShared(card);
    try { if (document.querySelectorAll(loose).length === members.length) candidates.push(loose); } catch (e) { /* ignore */ }
    if (card.parentElement && card.parentElement.parentElement) {
      candidates.push(sig(card.parentElement.parentElement) + " " + best.groupSel);
    }

    // title: the clicked text, or the most prominent text in the card if the click was on the card itself
    let titleEl = el;
    const leavesOfEl = textLeaves(el);
    if (el === card || leavesOfEl.length > 1) titleEl = biggestTextLeaf(el === card ? card : el) || el;
    else if (!ownText(el) && leavesOfEl.length === 1) titleEl = leavesOfEl[0];

    const fields = {
      title: { selectors: titleEl === card ? [] : fieldSelectors(card, titleEl, members, true), attr: null },
    };

    // apply url: the link around the title, else the card's first real link
    let link = titleEl.closest("a[href]");
    if (link && (link === card || card.contains(link))) {
      fields.apply_url = { selectors: link === card ? [] : fieldSelectors(card, link, members, false), attr: "href" };
    } else if (link && link.contains(card)) {
      fields.apply_url = { selectors: ["a[href]"], attr: "href", closest: true };
    } else {
      link = [...card.querySelectorAll("a[href]")].find((x) => !/^(#|javascript:)/i.test(x.getAttribute("href")));
      if (link) fields.apply_url = { selectors: fieldSelectors(card, link, members, false), attr: "href" };
    }

    // other fields: compare the same position across many cards
    const titleKey = pathSelector(card, titleEl);
    const sampleMembers = members.slice(0, 50);
    const groups = new Map();
    for (const m of sampleMembers) {
      const seen = new Set();
      for (const raw of textLeaves(m)) {
        const leaf = promote(raw, m);
        const key = pathSelector(m, leaf) || ":self";
        if (key === titleKey || seen.has(key)) continue;
        if (m === card && (leaf === titleEl || titleEl.contains(leaf) || leaf.contains(titleEl))) continue;
        seen.add(key);
        if (!groups.has(key)) groups.set(key, { key, values: [], leaf: null });
        const g = groups.get(key);
        g.values.push(textOf(leaf));
        if (m === card) g.leaf = leaf;
      }
    }
    const frac = (g, re) => g.values.filter((v) => re.test(v)).length / g.values.length;
    let pool = [...groups.values()].filter((g) => g.leaf && g.values.length >= Math.max(1, sampleMembers.length * 0.5));
    const take = (name, scoreFn, min) => {
      let bestG = null, bestS = min;
      for (const g of pool) { const s = scoreFn(g); if (s >= bestS) { bestG = g; bestS = s; } }
      if (!bestG) return;
      fields[name] = { selectors: fieldSelectors(card, bestG.leaf, members, true), attr: null };
      pool = pool.filter((g) => g !== bestG);
    };
    take("location", (g) => frac(g, LOC_RE), 0.5);
    take("posted", (g) => frac(g, DATE_RE), 0.5);
    take("department", (g) => {
      const avg = g.values.reduce((s, v) => s + v.length, 0) / g.values.length;
      if (avg > 60) return 0;
      const distinct = new Set(g.values).size;
      const vocab = frac(g, DEPT_RE);
      if (vocab >= 0.4) return 1 + vocab;
      return distinct >= 2 && distinct / g.values.length <= 0.6 ? 0.5 : 0;
    }, 0.5);

    const id = idAttribute(card, members);
    if (id) fields.job_id = id;

    return { count: members.length, card: { candidates }, fields, attributes: cardAttributes(card) };
  }

  function inferField(el, cardCandidates) {
    let members = [];
    for (const c of cardCandidates) {
      try { members = [...document.querySelectorAll(c)]; } catch (e) { continue; }
      if (members.length) break;
    }
    const card = members.find((m) => m.contains(el));
    if (!card) return null;
    let leaf = iconWithin(el, card) ? iconWithin(el, card).parentElement : el;  // clicked the "place" icon
    if (!ownText(leaf)) {
      const leaves = textLeaves(leaf);
      if (leaves.length === 1) leaf = leaves[0];  // wrapper around one text element → that element
      // several text pieces (e.g. "Sunnyvale" + "; Atlanta" + "; +5 more") → keep the container
    }
    leaf = promote(leaf, card);
    if (leaf === card) return { selectors: [], attr: null };
    return { selectors: fieldSelectors(card, leaf, members, true), attr: null };
  }

  // ── Highlighting ────────────────────────────────────────────────────
  let outlined = [];
  function highlight(cardCandidates) {
    clearHighlight();
    for (const c of cardCandidates) {
      let els = [];
      try { els = [...document.querySelectorAll(c)]; } catch (e) { continue; }
      if (!els.length) continue;
      for (const e of els) {
        outlined.push([e, e.style.outline, e.style.outlineOffset]);
        e.style.outline = "2px solid #f97316";
        e.style.outlineOffset = "-2px";
      }
      return els.length;
    }
    return 0;
  }
  function clearHighlight() {
    for (const [e, o, off] of outlined) { e.style.outline = o; e.style.outlineOffset = off; }
    outlined = [];
  }

  let hoverBox = null;
  function ensureHover() {
    if (hoverBox && hoverBox.isConnected) return hoverBox;
    if (!document.documentElement) return null;
    const host = document.createElement("div");
    host.id = HL_ID;
    host.style.cssText = "all:initial;position:fixed;pointer-events:none;z-index:2147483646;border:2px solid #22c55e;background:rgba(34,197,94,.12);border-radius:3px;display:none;";
    document.documentElement.appendChild(host);
    hoverBox = host;
    return host;
  }
  function showHover(el) {
    const box = ensureHover();
    if (!box) return;
    if (!el) { box.style.display = "none"; return; }
    const r = el.getBoundingClientRect();
    Object.assign(box.style, { display: "block", left: r.left + "px", top: r.top + "px", width: r.width + "px", height: r.height + "px" });
  }
  const armed = () => state.mode !== "off" && !paused;

  // ── Overlay (top frame) ─────────────────────────────────────────────
  const STYLE = `
    .panel{font:13px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#f9fafb;background:#111827;
      border:1px solid #374151;border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.35);width:400px;max-width:calc(100vw - 32px);overflow:hidden}
    .head{display:flex;align-items:center;gap:6px;padding:10px 12px;background:#1f2937}
    .title{font-weight:600;flex:1}
    .body{padding:10px 12px;max-height:55vh;overflow:auto}
    .collapsed .body{display:none}
    .msg{white-space:pre-wrap}
    .status{margin-top:6px;color:#fbbf24;white-space:pre-wrap}
    .status:empty,.preview:empty{display:none}
    .preview{margin-top:8px;overflow:auto}
    table{border-collapse:collapse;font-size:11px;width:100%}
    th,td{border-bottom:1px solid #374151;padding:3px 4px;text-align:left;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    th{color:#9ca3af;font-weight:500}
    .btns{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
    .btns:empty{display:none}
    button{font:inherit;cursor:pointer;border-radius:8px;border:1px solid #4b5563;background:#374151;color:#f9fafb;padding:5px 10px}
    button.primary{background:#f97316;border-color:#f97316;color:#111827;font-weight:600}
    button.mini{padding:1px 7px}
    .badge{font-size:11px;color:#111827;background:#22c55e;border-radius:6px;padding:1px 6px}
    .badge.paused{background:#fbbf24}
  `;

  function ensureOverlay() {
    if (!isTop || !document.documentElement) return null;
    let host = document.getElementById(HOST_ID);
    if (host && host.shadowRoot) return host.shadowRoot;
    host = document.createElement("div");
    host.id = HOST_ID;
    host.style.cssText = "all:initial;position:fixed;z-index:2147483647;right:16px;bottom:16px;";
    const root = host.attachShadow({ mode: "open" });
    // Built with createElement, never innerHTML: sites enforcing Trusted Types (e.g. Google) reject innerHTML.
    const el = (tag, cls, attrs = {}, text = "") => {
      const node = document.createElement(tag);
      if (cls) node.className = cls;
      for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
      if (text) node.textContent = text;
      return node;
    };
    const style = el("style");
    style.textContent = STYLE;
    const head = el("div", "head");
    head.append(
      el("span", "title"), el("span", "badge"),
      el("button", "mini", { "data-onboard-btn": "__move", title: "Move" }, "⇅"),
      el("button", "mini", { "data-onboard-btn": "__min", title: "Collapse" }, "–"),
    );
    const body = el("div", "body");
    body.append(el("div", "msg"), el("div", "status"), el("div", "preview"), el("div", "btns"));
    const panel = el("div", "panel");
    panel.append(head, body);
    root.append(style, panel);
    root.addEventListener("click", (e) => {
      const b = e.target.closest("[data-onboard-btn]");
      if (!b) return;
      e.stopPropagation();
      const id = b.dataset.onboardBtn;
      if (id === "__min") collapsed = !collapsed;
      else if (id === "__move") atTop = !atTop;
      else if (id === "__pause") paused = !paused;
      else if (id === "__popup") {
        state.popupRecording = !state.popupRecording;
        send({ type: state.popupRecording ? "record_popup" : "cancel_popup" });
      }
      else send({ type: "button", id, step: state.step });
      render();
    });
    document.documentElement.appendChild(host);
    return root;
  }

  function render() {
    if (!armed() && !state.popupRecording) showHover(null);
    if (!isTop) return;
    const root = ensureOverlay();
    if (!root) return;
    const host = root.host;
    host.style.display = state.step ? "block" : "none";
    host.style.top = atTop ? "16px" : "auto";
    host.style.bottom = atTop ? "auto" : "16px";
    root.querySelector(".panel").classList.toggle("collapsed", collapsed);
    root.querySelector(".title").textContent = state.title || "Onboarding";
    const badge = root.querySelector(".badge");
    badge.textContent = state.mode === "off" ? "" : paused ? "paused" : state.mode === "intercept" ? "picking" : "recording";
    badge.className = "badge" + (paused ? " paused" : "");
    badge.style.display = state.mode === "off" ? "none" : "inline";
    root.querySelector(".msg").textContent = state.message || "";
    root.querySelector(".status").textContent = state.popupRecording
      ? "● Recording a popup: click its close / accept button. That click goes through and is replayed on every run."
      : (state.status || "");

    const preview = root.querySelector(".preview");
    preview.textContent = "";
    const rows = Array.isArray(state.preview) ? state.preview : [];
    if (rows.length) {
      const cols = ["title", "location", "department", "posted", "apply_url"].filter((c) => rows.some((r) => r[c]));
      const table = document.createElement("table");
      const head = table.insertRow();
      for (const c of cols) { const th = document.createElement("th"); th.textContent = c; head.appendChild(th); }
      for (const r of rows) {
        const tr = table.insertRow();
        for (const c of cols) { const td = tr.insertCell(); td.textContent = r[c] || ""; td.title = r[c] || ""; }
      }
      preview.appendChild(table);
    }

    const btns = root.querySelector(".btns");
    btns.textContent = "";
    const list = [...(state.buttons || [])];
    if (state.mode !== "off") list.push({ id: "__pause", label: paused ? "Resume picking" : "Pause (let me click around)" });
    if (state.step && state.step !== "done") {
      list.push({ id: "__popup", label: state.popupRecording ? "Cancel popup recording"
        : `Record popup${state.popupCount ? ` (${state.popupCount} saved)` : ""}` });
    }
    for (const b of list) {
      const el = document.createElement("button");
      el.textContent = b.label;
      el.dataset.onboardBtn = b.id;
      if (b.primary) el.className = "primary";
      btns.appendChild(el);
    }
  }

  function setState(s) {
    Object.assign(state, s || {});
    paused = false;
    render();
  }

  // ── Event capture ───────────────────────────────────────────────────
  const POINTER_EVENTS = ["pointerdown", "mousedown", "pointerup", "mouseup", "click", "dblclick", "auxclick", "touchstart", "touchend"];

  function mark(el, step) {
    for (const e of document.querySelectorAll(`[data-onboard-target="${step}"]`)) e.removeAttribute("data-onboard-target");
    el.setAttribute("data-onboard-target", step);
  }

  function onPointer(e) {
    if (inOverlay(e.target)) return;
    const raw = e.composedPath()[0];
    if (raw && raw.closest && raw.closest("[data-onboard-auto]")) return;  // the popup watcher's own clicks
    if (state.popupRecording && !paused) {
      // record the popup's close button and let the click through so the popup actually closes
      if (e.type === "click") {
        const el = normalizeTarget(raw, "popup");
        state.popupRecording = false;
        render();
        if (el) send({ type: "popup", descriptor: describe(el), frameUrl: location.href });
      }
      return;
    }
    if (!armed()) return;
    if (state.mode === "intercept") {
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      if (e.type !== "click") return;
      const el = normalizeTarget(raw, state.step);
      if (!el) return;
      mark(el, state.step);
      state.mode = "off";  // one pick per arm; Python re-arms the next step
      render();
      send({ type: "pick", step: state.step, descriptor: describe(el), frameUrl: location.href, isTop });
    } else if (state.mode === "passive" && e.type === "click") {
      const el = normalizeTarget(raw, state.step);
      if (el) send({ type: "click", step: state.step, descriptor: describe(el), frameUrl: location.href });
    }
  }
  for (const t of POINTER_EVENTS) window.addEventListener(t, onPointer, true);

  let inputTimer = null;
  // Typed text is only ever read from real text inputs: an Enter pressed on <body> must not
  // turn the whole page's text into the "query".
  const inputValue = (el) => (el.matches(INPUT_LIKE) ? ("value" in el ? el.value : clean(el.innerText)) : null);

  window.addEventListener("input", (e) => {
    if (!armed() || state.mode !== "passive" || inOverlay(e.target)) return;
    const el = e.composedPath()[0];
    if (!el || el.nodeType !== 1 || inputValue(el) === null) return;
    clearTimeout(inputTimer);
    inputTimer = setTimeout(() => {
      send({ type: "input", step: state.step, value: inputValue(el), descriptor: describe(el) });
    }, 250);
  }, true);

  window.addEventListener("keydown", (e) => {
    if (!armed() || state.mode !== "passive" || e.key !== "Enter" || inOverlay(e.target)) return;
    const el = e.composedPath()[0];
    if (!el || el.nodeType !== 1 || inputValue(el) === null) return;
    send({ type: "key", key: "Enter", step: state.step, value: inputValue(el), descriptor: describe(el) });
  }, true);

  window.addEventListener("mousemove", (e) => {
    const recording = state.popupRecording && !paused;
    if ((!armed() && !recording) || inOverlay(e.target)) { showHover(null); return; }
    showHover(normalizeTarget(e.composedPath()[0], recording ? "popup" : state.step));
  }, true);

  window.__onboard = {
    state, setState, describe, inferCard, inferField, highlight, clearHighlight,
    target: (step) => document.querySelector(`[data-onboard-target="${step}"]`),
  };

  // Restore the current step after every navigation (the overlay is rebuilt per document)
  const boot = async () => {
    try {
      if (window.__onboardHello) setState(await window.__onboardHello());
    } catch (e) { /* not an onboarding session */ }
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
  setInterval(() => { if (isTop && state.step && !document.getElementById(HOST_ID)) render(); }, 1000);
})();
