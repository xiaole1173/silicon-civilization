/* theme.js — 主题切换 + 全站导航（零依赖） */
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

  // ---- 全站导航 ----
  var PAGES = [
    ["会话台", "chat.html"],
    ["模型管理", "models.html"],
    ["狼人杀观察台", "werewolf.html"],
    ["回放台", "../viz/index.html"]
  ];

  function prefix() {
    return location.pathname.indexOf("/viz/") >= 0 ? "../web/" : "";
  }

  function currentName() {
    var f = location.pathname.split("/").pop() || "";
    if (!f || f === "index.html") {
      return location.pathname.indexOf("/viz/") >= 0 ? "../viz/index.html" : "index.html";
    }
    return f;
  }

  function buildNav() {
    var nav = document.createElement("nav");
    nav.className = "topnav";
    var cur = currentName();
    PAGES.forEach(function (p) {
      var a = document.createElement("a");
      a.href = prefix() + p[1];
      a.textContent = p[0];
      var target = p[1].split("/").pop();
      if (target === cur || (p[1] === "../viz/index.html" && location.pathname.indexOf("/viz/") >= 0)) {
        a.className = "on";
      }
      nav.appendChild(a);
    });
    return nav;
  }

  document.addEventListener("DOMContentLoaded", function () {
    var bar = document.querySelector("header");
    if (!bar) {
      // 没有 header 的页面（旧观察台/回放台）：顶部插一条独立导航
      bar = document.createElement("div");
      bar.className = "topbar-fallback";
      document.body.insertBefore(bar, document.body.firstChild);
    }
    if (!bar.querySelector(".topnav")) {
      var nav = buildNav();
      var h1 = bar.querySelector("h1");
      if (h1 && h1.nextSibling) {
        bar.insertBefore(nav, h1.nextSibling);
      } else if (h1) {
        bar.appendChild(nav);
      } else {
        bar.insertBefore(nav, bar.firstChild);
      }
    }

    if (!bar.querySelector(".theme-toggle")) {
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
    }
  });
})();
