/* theme.js — 主题切换（light/dark），零依赖 */
(function () {
  var KEY = "dsh-theme";
  function apply(mode) {
    document.documentElement.setAttribute("data-theme", mode);
    try { localStorage.setItem(KEY, mode); } catch (e) {}
  }
  var saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) {}
  var forced = (location.search.match(/[?&]theme=(light|dark)/) || [])[1];
  apply(forced || saved || "light");

  document.addEventListener("DOMContentLoaded", function () {
    var bar = document.querySelector("header");
    if (!bar || bar.querySelector(".theme-toggle")) return;
    var btn = document.createElement("button");
    btn.className = "theme-toggle";
    btn.title = "切换深浅色";
    btn.setAttribute("aria-label", "切换深浅色");
    btn.textContent = document.documentElement.getAttribute("data-theme") === "dark" ? "浅" : "深";
    btn.onclick = function () {
      var now = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      apply(now);
      btn.textContent = now === "dark" ? "浅" : "深";
    };
    bar.appendChild(btn);
  });
})();
