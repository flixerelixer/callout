// FragSubs website: the live caption demo and the latest-version line.

(function () {
  "use strict";

  const LINES = [
    { who: "artyom", lang: "RU", text: "Two on B, one is low.", orig: "Двое на Б, один лоу.", latin: "Dvoe na B, odin lou." },
    { who: "Kuba", lang: "PL", text: "Save your rifle, we buy next round.", orig: "Sejwuj karabin, kupujemy w następnej." },
    { who: "efe", lang: "TR", text: "I'm smoking mid, I've got the AWP.", orig: "Ortaya smoke atıyorum, AWP bende." },
    { who: "dmytro", lang: "UK", text: "He's on banana, with a shotgun.", orig: "Він на банані, з дробовиком.", latin: "Vin na banani, z drobovykom." },
    { who: "Rafa", lang: "PT", text: "Can you drop me a weapon?", orig: "Dropa uma arma pra mim?" },
    { who: "li.wei", lang: "ZH", text: "Careful, they're on B!", orig: "小心，他们在B点！", latin: "xiǎo xīn, tā men zài B diǎn!" },
    { who: "Jonas", lang: "DE", text: "One is still in the tunnel.", orig: "Einer ist noch im Tunnel." },
    { who: "sasha_k", lang: "RU", text: "Don't peek, wait for the flash.", orig: "Не пикай, жди флешку.", latin: "Ne pikay, zhdi fleshku." },
  ];
  const MAX_ON_SCREEN = 3;
  const ON_SCREEN_MS = 7000;

  const list = document.getElementById("captions");
  const voice = document.querySelector(".voice");
  const voiceName = document.getElementById("voice-name");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function caption(line) {
    const li = document.createElement("li");
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

  if (list) {
    if (reduceMotion) {
      // A still picture instead of the animation.
      LINES.slice(0, MAX_ON_SCREEN).forEach((l) => list.append(caption(l)));
    } else {
      let i = 0;
      let visible = true;
      let timer = null;

      const step = () => {
        timer = null;
        if (!visible || document.hidden) return;
        const line = LINES[i % LINES.length];
        i += 1;
        // Someone talks for a moment (like the gold voice indicator)...
        voiceName.textContent = line.who;
        voice.classList.add("on");
        const talk = 900 + line.text.length * 28;
        setTimeout(() => {
          voice.classList.remove("on");
          // ...and the caption appears shortly after they stop.
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

      const resume = () => { if (!timer && visible && !document.hidden) timer = setTimeout(step, 400); };
      if ("IntersectionObserver" in window) {
        new IntersectionObserver((entries) => {
          visible = entries[0].isIntersecting;
          resume();
        }).observe(list.closest(".scene"));
      }
      document.addEventListener("visibilitychange", resume);
      resume();
    }
  }

  // Latest version and download size, straight from the GitHub release.
  const info = document.getElementById("release-info");
  if (info && window.fetch) {
    fetch("https://api.github.com/repos/fgmrkt/callout/releases/latest", { headers: { Accept: "application/vnd.github+json" } })
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
