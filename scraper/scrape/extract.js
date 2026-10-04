// Extract fields from job-card elements. Used by both the scraper (evaluate_all on the
// card locator) and the onboarding wizard's preview, so what you confirm is what you get.
// fields: { name: { selectors: [css...], attr: null | "href" | "<attr>", closest: bool } }
(cards, fields) => {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 || r.height > 0;
  };
  const absolute = (raw) => {
    if (!raw) return null;
    try { return new URL(raw, document.baseURI).href; } catch (e) { return raw; }
  };
  const ICON = 'svg, [aria-hidden="true"], i[class*="icon"], i[class*="fa-"], [class*="material-icons"], [class*="material-symbols"]';
  const textOf = (el) => {
    if (!el.querySelector(ICON)) return el.innerText || el.textContent || "";
    let out = "";
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      let p = n.parentElement, icon = false;
      for (let a = p; a && a !== el.parentElement; a = a.parentElement) if (a.matches(ICON)) { icon = true; break; }
      if (!icon && p && p.getClientRects().length) out += n.textContent;
    }
    return out;
  };
  const pick = (card, spec) => {
    const sels = spec.selectors || [];
    if (!sels.length) return card;
    for (const s of sels) {
      try {
        const el = spec.closest ? card.closest(s) : card.querySelector(s);
        if (el) return el;
      } catch (e) { /* invalid selector, try the next one */ }
    }
    return null;
  };
  const read = (el, spec) => {
    if (!el) return null;
    if (spec.attr === "href") {
      const a = el.hasAttribute("href") ? el : (el.closest("a[href]") || el.querySelector("a[href]"));
      return a ? absolute(a.getAttribute("href")) : null;
    }
    if (spec.attr) return el.getAttribute(spec.attr);
    return textOf(el).replace(/\s+\n/g, "\n").trim();
  };
  return cards.filter(visible).map((card) => {
    const out = {};
    for (const [name, spec] of Object.entries(fields)) {
      const value = read(pick(card, spec), spec);
      if (value) out[name] = value;
    }
    return out;
  });
}
