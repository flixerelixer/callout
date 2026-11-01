// FragSubs website: the live caption demo, the map picker and the latest-version line.

(function () {
  "use strict";

  const MAP_NAMES = {};
  for (const m of window.FRAGSUBS_MAPS || []) MAP_NAMES[m.key] = m.name;

  // ------------------------------------------------------------------ demo
  // A few teammates per map. When the map changes, so do the callouts.
  const LINES = [
    { map: "de_mirage", who: "artyom", lang: "RU", text: "Two in Palace, one in Apps.", orig: "Двое на паласе, один в аппсах.", latin: "Dvoe na palase, odin v appsakh." },
    { map: "de_mirage", who: "Kuba", lang: "PL", text: "Smoke Jungle, I'm going Connector.", orig: "Dym na Jungle, idę na Connector." },
    { map: "de_mirage", who: "efe", lang: "TR", text: "I've got the AWP, I'm holding Window.", orig: "AWP bende, Window'u tutuyorum." },
    { map: "de_inferno", who: "sasha_k", lang: "RU", text: "Two on Banana, throw a molly in Coffins.", orig: "Двое на банане, кидай молик в гробы.", latin: "Dvoe na banane, kiday molik v groby." },
    { map: "de_inferno", who: "dmytro", lang: "UK", text: "He's in Pit, one HP.", orig: "Він у піті, один хп.", latin: "Vin u piti, odyn khp." },
    { map: "de_inferno", who: "Jonas", lang: "DE", text: "One is still in Library.", orig: "Einer ist noch in Library." },
    { map: "de_dust2", who: "li.wei", lang: "ZH", text: "Two in B tunnels, I'm going Mid Doors.", orig: "两个在B洞，我去中门。", latin: "liǎng gè zài B dòng, wǒ qù zhōng mén." },
    { map: "de_dust2", who: "Rafa", lang: "PT", text: "Can you drop me a gun? I'm at Goose.", orig: "Dropa uma arma pra mim? Tô no Goose." },
    { map: "de_nuke", who: "dmytro", lang: "UK", text: "One in Heaven, the other on Ramp.", orig: "Один у хевені, другий на ремпі.", latin: "Odyn u kheveni, druhyy na rempi." },
    { map: "de_nuke", who: "sasha_k", lang: "RU", text: "Rotate to Secret, they're going Outside.", orig: "Ротейт в секрет, они идут на аутсайд.", latin: "Roteyt v sekret, oni idut na autsayd." },
  ];
  const MAX_ON_SCREEN = 3;
  const ON_SCREEN_MS = 7000;

  const scene = document.querySelector(".scene");
  const list = document.getElementById("captions");
  const voice = document.querySelector(".voice");
  const voiceName = document.getElementById("voice-name");
  const mapName = document.getElementById("map-name");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function caption(line, tagName = "li") {
    const li = document.createElement(tagName);
    li.className = "cap";
    const tag = document.createElement("span");
    tag.className = "cap-tag";
    tag.textContent = line.lang;
    const text = document.createElement("span");
    text.className = "cap-text";
    text.textContent = line.text;
    li.append(tag, text);
    for (const extra of [line.orig, line.latin]) {
      if (!extra) continue;
      const o = document.createElement("span");
      o.className = "cap-orig";
      o.textContent = extra;
      li.append(o);
    }
    return li;
  }

  function remove(li) {
    if (!li.isConnected || li.classList.contains("out")) return;
    li.classList.add("out");
    setTimeout(() => li.remove(), 500);
  }

  function showMap(key) {
    scene.dataset.map = key;
    mapName.textContent = MAP_NAMES[key] || key;
  }

  if (list && scene) {
    if (reduceMotion) {
      // A still picture instead of the animation.
      LINES.slice(0, MAX_ON_SCREEN).forEach((l) => list.append(caption(l)));
    } else {
      // Start with one subtitle already on screen, so the demo never opens empty.
      const first = caption(LINES[0]);
      list.append(first);
      setTimeout(() => remove(first), ON_SCREEN_MS);
      let i = 1;
      let visible = true;
      let timer = null;

      const speak = (line) => {
        // Someone talks for a moment (like the game's voice indicator)...
        voiceName.textContent = line.who;
        voice.classList.add("on");
        const talk = 900 + line.text.length * 28;
        setTimeout(() => {
          voice.classList.remove("on");
          // ...and the subtitle appears shortly after they stop.
          setTimeout(() => {
            const li = caption(line);
            list.append(li);
            const live = list.querySelectorAll(".cap:not(.out)");
            if (live.length > MAX_ON_SCREEN) remove(live[0]);
            setTimeout(() => remove(li), ON_SCREEN_MS);
            timer = setTimeout(step, 1300);
          }, 450);
        }, talk);
      };

      const step = () => {
        timer = null;
        if (!visible || document.hidden) return;
        const line = LINES[i % LINES.length];
        i += 1;
        if (line.map === scene.dataset.map) {
          speak(line);
          return;
        }
        // Next match: the old subtitles go, the new map loads.
        list.querySelectorAll(".cap").forEach(remove);
        scene.classList.add("switching");
        setTimeout(() => {
          showMap(line.map);
          scene.classList.remove("switching");
          timer = setTimeout(() => speak(line), 900);
        }, 650);
      };

      const resume = () => { if (!timer && visible && !document.hidden) timer = setTimeout(step, 400); };
      if ("IntersectionObserver" in window) {
        new IntersectionObserver((entries) => {
          visible = entries[0].isIntersecting;
          resume();
        }).observe(scene);
      }
      document.addEventListener("visibilitychange", resume);
      resume();
    }
  }

  // ------------------------------------------------------------------ map picker
  const EXAMPLES = {
    de_ancient: { lang: "TR", text: "Two in Temple, one in Elbow.", orig: "İkisi Temple'da, biri Elbow'da." },
    de_anubis: { lang: "PL", text: "One on Bridge, two in Ruins.", orig: "Jeden na Bridge, dwóch w Ruins." },
    de_cache: { lang: "DE", text: "Two in Checkers, one in Squeaky.", orig: "Zwei in Checkers, einer in Squeaky." },
    de_dust2: { lang: "RU", text: "Two on Long Doors, one at Goose.", orig: "Двое на лонг дорс, один на гусе.", latin: "Dvoe na long dors, odin na guse." },
    de_inferno: { lang: "RU", text: "Two on Banana, throw a molly in Coffins.", orig: "Двое на банане, кидай молик в гробы.", latin: "Dvoe na banane, kiday molik v groby." },
    de_mirage: { lang: "RU", text: "Two in Palace, one in Apps.", orig: "Двое на паласе, один в аппсах.", latin: "Dvoe na palase, odin v appsakh." },
    de_nuke: { lang: "UK", text: "One in Heaven, the other on Ramp.", orig: "Один у хевені, другий на ремпі.", latin: "Odyn u kheveni, druhyy na rempi." },
    de_overpass: { lang: "PT", text: "Two in Monster, one in Toilets.", orig: "Dois no Monster, um no Toilets." },
    de_vertigo: { lang: "ZH", text: "Two on A Ramp, one on Stairs.", orig: "两个在A坡，一个在楼梯。", latin: "liǎng gè zài A pō, yí gè zài lóu tī." },
  };

  const tabs = document.getElementById("map-tabs");
  const panel = document.getElementById("map-panel");
  const mapScene = document.getElementById("map-scene");
  const chips = document.getElementById("map-chips");
  const count = document.getElementById("map-count");
  const maps = window.FRAGSUBS_MAPS || [];

  function said(text, callout) {
    // Is this callout in the example sentence (as whole words)?
    const escaped = callout.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(`(^|[^\\p{L}])${escaped}([^\\p{L}]|$)`, "iu").test(text);
  }

  function selectMap(key, focus) {
    const m = maps.find((x) => x.key === key);
    if (!m) return;
    for (const b of tabs.querySelectorAll(".map-tab")) {
      const on = b.dataset.key === key;
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
      if (on) {
        panel.setAttribute("aria-labelledby", b.id);
        if (focus) b.focus();
      }
    }
    mapScene.dataset.map = key;
    const ex = EXAMPLES[key];
    const old = document.getElementById("map-cap");
    if (ex && old) {
      const fresh = caption(ex, "div");
      fresh.id = "map-cap";
      fresh.classList.add("fresh");
      old.replaceWith(fresh);
    }
    count.textContent = `${m.name}: ${m.callouts.length} callouts FragSubs listens for, plus common words like AWP, smoke, molly and one HP.`;
    chips.replaceChildren(...m.callouts.map((c) => {
      const li = document.createElement("li");
      li.textContent = c;
      if (ex && said(ex.text, c)) li.className = "on";
      return li;
    }));
  }

  if (tabs && panel && maps.length) {
    maps.forEach((m) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "map-tab";
      b.id = `tab-${m.key}`;
      b.dataset.key = m.key;
      b.setAttribute("role", "tab");
      b.setAttribute("aria-controls", "map-panel");
      b.textContent = m.name;
      b.addEventListener("click", () => selectMap(m.key, false));
      tabs.append(b);
    });
    tabs.addEventListener("keydown", (e) => {
      const keys = maps.map((m) => m.key);
      const now = keys.indexOf(mapScene.dataset.map);
      let next = null;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") next = (now + 1) % keys.length;
      if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = (now - 1 + keys.length) % keys.length;
      if (e.key === "Home") next = 0;
      if (e.key === "End") next = keys.length - 1;
      if (next === null) return;
      e.preventDefault();
      selectMap(keys[next], true);
    });
    selectMap("de_mirage", false);
  }

  // ------------------------------------------------------------------ release
  // Latest version and download size, straight from the GitHub release.
  const info = document.getElementById("release-info");
  if (info && window.fetch) {
    fetch("https://api.github.com/repos/flixerelixer/callout/releases/latest", { headers: { Accept: "application/vnd.github+json" } })
      .then((r) => (r.ok ? r.json() : null))
      .then((rel) => {
        if (!rel || !rel.tag_name) return;
        const setup = (rel.assets || []).find((a) => a.name === "FragSubs-Setup.exe");
        const size = setup ? `, ${Math.round(setup.size / 1e6)} MB` : "";
        info.textContent = `Version ${rel.tag_name.replace(/^v/, "")} for Windows 10 and 11${size}. Free, and it updates itself.`;
      })
      .catch(() => {});
  }
})();
