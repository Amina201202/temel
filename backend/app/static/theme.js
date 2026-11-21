// tema: ag ve qaranliq. Secim yadda qalir, ilk defe cihazin oz rejimi goturulur
(function () {
  const KEY = "temel_theme";
  const root = document.documentElement;

  function apply(t) {
    root.dataset.theme = t;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = t === "dark" ? "#11121A" : "#3D4BE0";
    document.querySelectorAll(".theme-btn").forEach((b) => {
      b.textContent = t === "dark" ? "☀️" : "🌙";
      const label = t === "dark" ? "Ağ temaya keç" : "Qaranlıq temaya keç";
      b.title = label;
      b.setAttribute("aria-label", label);
    });
  }

  let saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) { /* */ }
  apply(saved || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));

  window.toggleTheme = function () {
    const next = root.dataset.theme === "dark" ? "light" : "dark";
    try { localStorage.setItem(KEY, next); } catch (e) { /* */ }
    apply(next);
  };

  document.addEventListener("DOMContentLoaded", () => {
    apply(root.dataset.theme);
    document.querySelectorAll(".theme-btn").forEach((b) => (b.onclick = window.toggleTheme));
  });
})();
