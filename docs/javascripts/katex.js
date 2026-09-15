// KaTeX wiring for pymdownx.arithmatex in `generic: true` mode.
// Re-runs on Material's instant-navigation event, not just on first load --
// without the subscription, every page after the first renders raw TeX.
document$.subscribe(({ body }) => {
  renderMathInElement(body, {
    delimiters: [
      { left: "$$", right: "$$", display: true },
      { left: "$", right: "$", display: false },
      { left: "\\(", right: "\\)", display: false },
      { left: "\\[", right: "\\]", display: true },
    ],
  });
});
