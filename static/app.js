(function () {
  "use strict";

  var state = { locations: [], stalls: {}, today: null, tab: "bin", insightStall: null, busy: false };
  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------- Helpers ----------
  function $(id) { return document.getElementById(id); }
  function fmt(n, d) { return Number(n).toFixed(d); }
  function money(n) { return "S$" + Math.round(n).toLocaleString("en-SG"); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return "&#" + c.charCodeAt(0) + ";"; }); }
  function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  var toastTimer;
  function toast(msg) {
    var t = $("toast"); t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.hidden = true; }, 2600);
  }

  function api(path, opts) {
    return fetch(path, opts).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (body) {
        if (!res.ok) {
          var msg = typeof body.detail === "string" ? body.detail : "Request failed (" + res.status + ")";
          throw new Error(msg);
        }
        return body;
      });
    });
  }

  function currentLocation() { return state.locations.filter(function (l) { return l.id === $("sel-location").value; })[0]; }
  function currentBin() { return currentLocation().bins[0]; }

  // ---------- Tabs ----------
  var tabs = ["bin", "insights", "compost", "proposal"];
  function showTab(name) {
    state.tab = name;
    tabs.forEach(function (t) {
      $("tab-" + t).setAttribute("aria-selected", t === name ? "true" : "false");
      $("view-" + t).hidden = t !== name;
    });
    if (name === "insights") loadInsights();
    if (name === "compost") loadCompost();
    if (name === "bin") loadBin();
    history.replaceState(null, "", "#" + name);
  }
  tabs.forEach(function (t) { $("tab-" + t).addEventListener("click", function () { showTab(t); }); });

  // ---------- Camera canvas (shown when no photo) ----------
  var cv = $("cam-canvas"), cx = cv.getContext("2d");
  function drawCam(fill, item) {
    var w = cv.width, h = cv.height;
    cx.clearRect(0, 0, w, h);
    cx.fillStyle = "#1a2520"; cx.beginPath(); cx.ellipse(w / 2, h * 0.58, w * 0.4, h * 0.36, 0, 0, Math.PI * 2); cx.fill();
    cx.strokeStyle = "#33463d"; cx.lineWidth = 4; cx.stroke();
    if (fill > 0) {
      cx.fillStyle = "#4a3b26"; cx.globalAlpha = 0.35 + fill * 0.5;
      cx.beginPath(); cx.ellipse(w / 2, h * 0.6, w * 0.34 * (0.5 + fill / 2), h * 0.28 * (0.5 + fill / 2), 0, 0, Math.PI * 2); cx.fill();
      cx.globalAlpha = 1;
    }
    if (item) {
      var r = 40 + Math.min(110, item.kg * 30 + 20);
      cx.fillStyle = "#C9A15B";
      for (var i = 0; i < 9; i++) {
        var a = (i / 9) * Math.PI * 2;
        cx.beginPath(); cx.arc(w / 2 + Math.cos(a) * r * 0.35, h * 0.56 + Math.sin(a) * r * 0.25, r * (0.3 + (i % 3) * 0.06), 0, Math.PI * 2); cx.fill();
      }
      var bx = w / 2 - r, by = h * 0.56 - r * 0.75, bw = r * 2, bh = r * 1.5, c = 18;
      cx.strokeStyle = "#8EE0A9"; cx.lineWidth = 3;
      [[bx, by, 1, 1], [bx + bw, by, -1, 1], [bx, by + bh, 1, -1], [bx + bw, by + bh, -1, -1]].forEach(function (p) {
        cx.beginPath(); cx.moveTo(p[0] + c * p[2], p[1]); cx.lineTo(p[0], p[1]); cx.lineTo(p[0], p[1] + c * p[3]); cx.stroke();
      });
    }
  }

  function animateNumber(el, to, decimals, ms) {
    return new Promise(function (resolve) {
      if (reduceMotion) { el.textContent = fmt(to, decimals); resolve(); return; }
      var start = performance.now();
      function step(now) {
        var p = Math.min(1, (now - start) / ms);
        el.textContent = fmt(to * (1 - Math.pow(1 - p, 3)), decimals);
        if (p < 1) requestAnimationFrame(step); else resolve();
      }
      requestAnimationFrame(step);
    });
  }

  // ---------- Live bin ----------
  function fillLocations() {
    var sel = $("sel-location"); sel.innerHTML = "";
    state.locations.forEach(function (l) {
      var o = document.createElement("option"); o.value = l.id; o.textContent = l.name + " food court"; sel.appendChild(o);
    });
  }
  function fillStalls() {
    var sel = $("sel-stall"); sel.innerHTML = "";
    currentLocation().stalls.forEach(function (s) {
      var o = document.createElement("option"); o.value = s.id; o.textContent = s.name; sel.appendChild(o);
    });
    fillDishes();
  }
  function fillDishes() {
    var sel = $("sel-dish"); sel.innerHTML = "<option value=''>No label</option>";
    state.stalls[$("sel-stall").value].menu.forEach(function (d) {
      var o = document.createElement("option"); o.value = d; o.textContent = d; sel.appendChild(o);
    });
  }
  function randomWeight(source) {
    return source === "plate" ? 0.04 + Math.random() * 0.21 : 1 + Math.random() * 5;
  }
  function selectedSource() { return document.querySelector('input[name="source"]:checked').value; }

  $("sel-location").addEventListener("change", function () { fillStalls(); loadBin(); });
  $("sel-stall").addEventListener("change", fillDishes);
  $("btn-scale").addEventListener("click", function () { $("in-weight").value = fmt(randomWeight(selectedSource()), 3); });

  function renderLoad(bin) {
    $("unit-id").textContent = "Bin " + bin.id + " · " + currentLocation().name;
    $("lcd-load").textContent = fmt(bin.load_kg, 1);
    $("lcd-cap").textContent = "/ " + fmt(bin.capacity_kg, 0) + " kg";
    var g = $("gauge");
    g.querySelector("i").style.width = Math.min(100, bin.fill_pct) + "%";
    g.classList.toggle("full", bin.fill_pct >= 85);
    if ($("cam-photo").hidden) drawCam(bin.load_kg / bin.capacity_kg, null);
  }

  function loadBin() {
    if (!state.locations.length) return Promise.resolve();
    var bin = currentBin();
    return Promise.all([
      api("/api/bins/" + bin.id),
      api("/api/drops?bin_id=" + bin.id + "&day=" + state.today + "&limit=500")
    ]).then(function (r) {
      renderLoad(r[0]);
      renderLog(r[1]);
    }).catch(function (e) { toast(e.message); });
  }

  function renderLog(drops) {
    var body = $("log-body"); body.innerHTML = "";
    drops.slice(0, 12).forEach(function (d) {
      var t = new Date(d.created_at);
      var by = d.classified_by === "claude" ? "Claude " + Math.round(d.confidence * 100) + "%" : d.classified_by === "device" ? "Device label" : "–";
      var tr = document.createElement("tr");
      tr.innerHTML = "<td class='num'>" + t.toLocaleTimeString("en-SG", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) + "</td>" +
        "<td>" + esc(state.stalls[d.stall_id].name) + "</td><td>" + esc(d.dish || "Unidentified") + "</td>" +
        "<td><span class='pill " + d.source + "'>" + (d.source === "plate" ? "Customer" : "Vendor") + "</span></td>" +
        "<td>" + by + "</td><td class='r'>" + fmt(d.weight_kg, 3) + "</td>";
      body.appendChild(tr);
    });
    $("log-count").textContent = drops.length;
    $("log-empty").hidden = drops.length > 0;
  }

  function postDrop(stallId, source, weight, dish, photo) {
    var fd = new FormData();
    fd.append("stall_id", stallId);
    fd.append("source", source);
    fd.append("weight_kg", fmt(weight, 3));
    if (dish) fd.append("dish", dish);
    if (photo) fd.append("image", photo);
    return api("/api/bins/" + currentBin().id + "/drops", { method: "POST", body: fd });
  }

  function showResult(res, photo) {
    var d = res.drop;
    var stall = state.stalls[d.stall_id];
    $("cam-dish").textContent = (d.dish || "Unidentified") + " · " + stall.name;
    $("cam-conf").textContent = d.classified_by === "claude" ? Math.round(d.confidence * 100) + "% · Claude"
      : d.classified_by === "device" ? "Device label" : photo ? "Not identified" : "No photo";
    var img = $("cam-photo");
    if (d.image_url) { img.src = d.image_url; img.hidden = false; }
    else { img.hidden = true; drawCam(0, { kg: d.weight_kg }); }
  }

  function setBusy(b) {
    state.busy = b;
    $("btn-drop").disabled = b; $("btn-rush").disabled = b;
  }

  $("drop-form").addEventListener("submit", function (e) {
    e.preventDefault();
    if (state.busy) return;
    var err = $("drop-error"); err.hidden = true;
    var weight = parseFloat($("in-weight").value);
    if (!(weight > 0 && weight <= 25)) {
      err.textContent = "Enter a weight between 0.001 and 25 kg, or press Read scale.";
      err.hidden = false; $("in-weight").focus(); return;
    }
    var photo = $("in-photo").files[0] || null;
    setBusy(true);
    $("cam").classList.add("scanning");
    $("unit-status").textContent = photo ? "Identifying" : "Weighing";
    $("cam-dish").textContent = photo ? "Identifying…" : "Weighing…";
    $("cam-conf").textContent = "–";
    $("lcd-weight").textContent = "0.000";
    postDrop($("sel-stall").value, selectedSource(), weight, $("sel-dish").value, photo)
      .then(function (res) {
        $("cam").classList.remove("scanning");
        showResult(res, photo);
        $("unit-status").textContent = "Saved";
        $("in-weight").value = ""; $("in-photo").value = "";
        return animateNumber($("lcd-weight"), res.drop.weight_kg, 3, 700);
      })
      .then(loadBin)
      .catch(function (e) {
        $("cam").classList.remove("scanning");
        $("unit-status").textContent = "Error";
        err.textContent = e.message; err.hidden = false;
      })
      .finally(function () { setBusy(false); });
  });

  $("btn-rush").addEventListener("click", function () {
    if (state.busy) return;
    setBusy(true);
    $("cam-photo").hidden = true;
    var stalls = currentLocation().stalls, n = 12, saved = 0;
    (function next() {
      if (n-- <= 0) return Promise.resolve();
      var s = stalls[Math.floor(Math.random() * stalls.length)];
      var dish = s.menu[Math.floor(Math.random() * s.menu.length)];
      $("cam").classList.add("scanning");
      return sleep(reduceMotion ? 50 : 350)
        .then(function () { return postDrop(s.id, "plate", randomWeight("plate"), dish, null); })
        .then(function (res) {
          saved++;
          $("cam").classList.remove("scanning");
          showResult(res, null);
          $("unit-status").textContent = "Saved";
          return animateNumber($("lcd-weight"), res.drop.weight_kg, 3, 300);
        })
        .then(loadBin)
        .then(next);
    })()
      .catch(function (e) { $("cam").classList.remove("scanning"); toast(e.message); })
      .finally(function () { setBusy(false); if (saved) toast("Saved " + saved + " weigh-ins"); });
  });

  // ---------- Insights ----------
  function renderChips() {
    var chips = $("stall-chips"); chips.innerHTML = "";
    Object.keys(state.stalls).forEach(function (id) {
      var b = document.createElement("button");
      b.type = "button"; b.textContent = state.stalls[id].name;
      b.setAttribute("aria-pressed", id === state.insightStall ? "true" : "false");
      b.addEventListener("click", function () { state.insightStall = id; renderChips(); loadInsights(); });
      chips.appendChild(b);
    });
  }

  function kpi(label, value, unit, cls) {
    return '<div class="kpi ' + cls + '"><span class="label">' + label + '</span><span class="v">' + value + '<small>' + unit + '</small></span></div>';
  }

  function renderChart(stall, rows, suggested) {
    if (!rows.length) { $("chart").innerHTML = '<p class="empty">No days with portions cooked yet.</p>'; return; }
    var W = 720, H = 280, L = 44, R = 12, T = 14, B = 40;
    var max = Math.max.apply(null, rows.map(function (r) { return r.prepared; }).concat([suggested || 0]));
    var step = max > 400 ? 100 : 50, top = Math.max(step, Math.ceil(max / step) * step);
    var y = function (v) { return T + (H - T - B) * (1 - v / top); };
    var bw = (W - L - R) / rows.length;
    var ink = cssVar("--ink"), muted = cssVar("--muted"), line = cssVar("--line"), acc = cssVar("--accent"), waste = cssVar("--waste");
    var out = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Portions sold and unsold per day for ' + esc(stall.name) + '">';
    for (var v = 0; v <= top; v += step) {
      out += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v) + '" y2="' + y(v) + '" stroke="' + line + '"/>';
      out += '<text x="' + (L - 8) + '" y="' + (y(v) + 4) + '" text-anchor="end" font-size="11" fill="' + muted + '" font-family="JetBrains Mono, monospace">' + v + '</text>';
    }
    rows.forEach(function (r, i) {
      var x = L + i * bw + bw * 0.18, w = bw * 0.64;
      var d = new Date(r.day + "T00:00:00");
      out += '<rect x="' + x + '" y="' + y(r.sold) + '" width="' + w + '" height="' + (y(0) - y(r.sold)) + '" fill="' + acc + '"><title>' + r.sold + ' sold</title></rect>';
      out += '<rect x="' + x + '" y="' + y(r.prepared) + '" width="' + w + '" height="' + (y(r.sold) - y(r.prepared)) + '" fill="' + waste + '"><title>' + r.unsold + ' unsold (' + fmt(r.unsold_kg, 1) + ' kg)</title></rect>';
      out += '<text x="' + (x + w / 2) + '" y="' + (H - B + 16) + '" text-anchor="middle" font-size="11" fill="' + (r.weekend ? muted : ink) + '" font-family="Public Sans, sans-serif">' + d.toLocaleDateString("en-SG", { weekday: "short" }) + '</text>';
      out += '<text x="' + (x + w / 2) + '" y="' + (H - B + 30) + '" text-anchor="middle" font-size="10" fill="' + muted + '" font-family="JetBrains Mono, monospace">' + d.getDate() + '/' + (d.getMonth() + 1) + '</text>';
    });
    if (suggested) {
      var sy = y(suggested);
      out += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + sy + '" y2="' + sy + '" stroke="' + ink + '" stroke-width="1.5" stroke-dasharray="6 4"/>';
      out += '<text x="' + (W - R - 4) + '" y="' + (sy - 6) + '" text-anchor="end" font-size="11" font-weight="600" fill="' + ink + '" font-family="Public Sans, sans-serif">Suggested weekday prep: ' + suggested + '</text>';
    }
    $("chart").innerHTML = out + "</svg>";
  }

  function loadInsights() {
    if (!state.insightStall) return;
    api("/api/stalls/" + state.insightStall + "/insights").then(function (data) {
      var s = data.stall, sg = data.suggestion, t = data.today;
      if (sg) {
        $("kpis").innerHTML =
          kpi("Cooked per weekday", Math.round(sg.avg_prepared), "portions", "") +
          kpi("Sold per weekday", Math.round(sg.avg_sold), "portions", "") +
          kpi("Unsold per weekday", Math.round(sg.avg_unsold), fmt(sg.waste_pct, 0) + "% of food", "warn") +
          kpi("Suggested prep", sg.suggested_prep, "portions", "hl");
        $("rec").innerHTML =
          '<span class="label">Recommendation for ' + esc(s.name) + '</span>' +
          '<h3>Cook <strong class="num">' + sg.suggested_prep + '</strong> portions on weekdays instead of about <span class="num">' + Math.round(sg.avg_prepared) + '</span>.</h3>' +
          '<p>That is <b class="num">' + sg.portions_saved_per_day + '</b> fewer portions a day, about <b class="num">' + fmt(sg.kg_saved_per_day, 1) + ' kg</b> less food thrown away and <b class="num">' + money(sg.sgd_saved_per_day) + '</b> saved in ingredients. Over a month of 22 trading days that is <b class="num">' + money(sg.sgd_saved_per_month) + '</b>.</p>' +
          '<p class="muted" style="font-size:0.85rem">Based on ' + sg.weekdays_used + ' weekdays. Suggested prep is average weekday sales plus half a standard deviation (' + fmt(sg.sd_sold, 1) + ' portions), so the stall rarely sells out.</p>';
      } else {
        $("kpis").innerHTML = "";
        $("rec").innerHTML = '<span class="label">Recommendation for ' + esc(s.name) + '</span><p>Needs at least 3 weekdays of portions cooked and closing weigh-ins before it can suggest a number.</p>';
      }
      renderChart(s, data.history, sg && sg.suggested_prep);
      $("in-prep").value = t.prepared == null ? "" : t.prepared;
      $("today").innerHTML = '<table><tbody>' +
        '<tr><td>Items weighed</td><td class="r">' + t.drops + '</td></tr>' +
        '<tr><td>Customer plate waste</td><td class="r">' + fmt(t.plate_kg, 2) + ' kg</td></tr>' +
        '<tr><td>Vendor unsold food</td><td class="r">' + fmt(t.unsold_kg, 2) + ' kg</td></tr>' +
        '<tr><td>Unsold portions (' + s.portion_g + ' g each)</td><td class="r">' + t.unsold_portions + '</td></tr>' +
        (t.prepared != null ? '<tr><td>Portions sold so far</td><td class="r">' + Math.max(0, t.prepared - t.unsold_portions) + '</td></tr>' : '') +
        '</tbody></table>';
    }).catch(function (e) { toast(e.message); });
  }

  $("prep-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var n = parseInt($("in-prep").value, 10);
    if (!(n >= 0)) { toast("Enter the number of portions cooked today."); return; }
    api("/api/stalls/" + state.insightStall + "/prep", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ day: state.today, portions: n })
    }).then(function () { toast("Saved " + n + " portions for today"); loadInsights(); })
      .catch(function (e) { toast(e.message); });
  });

  // ---------- Compost ----------
  function loadCompost() {
    api("/api/compost").then(function (c) {
      $("compost-kg").textContent = fmt(c.diverted_kg, 1);
      $("compost-out").textContent = fmt(c.compost_out_kg, 1) + " kg";
      $("transfers").textContent = c.transfers;
      $("tank-compost").querySelector("i").style.height = Math.min(100, c.diverted_kg / 1000 * 100) + "%";
      var wrap = $("bins"); wrap.innerHTML = "";
      c.bins.forEach(function (b) {
        var loc = state.locations.filter(function (l) { return l.id === b.location_id; })[0];
        var el = document.createElement("div");
        el.className = "panel";
        el.innerHTML = '<h3>Bin ' + esc(b.id) + ' · ' + esc(loc ? loc.name : "") + '</h3>' +
          '<div class="tank"><div class="tank-vis"><i style="height:' + Math.min(100, b.fill_pct) + '%"></i></div>' +
          '<div class="tank-stats"><div class="label">Waiting to be composted</div>' +
          '<div class="v">' + fmt(b.load_kg, 1) + ' kg</div>' +
          '<p class="muted">' + (b.load_kg === 0 ? "Bin is empty." : fmt(b.fill_pct, 0) + "% full.") + '</p>' +
          '<div class="btn-row"><button class="btn" type="button"' + (b.load_kg === 0 ? " disabled" : "") + '>Transfer to compost</button></div></div></div>';
        el.querySelector("button").addEventListener("click", function () {
          api("/api/bins/" + b.id + "/transfers", { method: "POST" })
            .then(function (t) { toast("Moved " + fmt(t.weight_kg, 1) + " kg from bin " + b.id + " to compost"); loadCompost(); })
            .catch(function (e) { toast(e.message); });
        });
        wrap.appendChild(el);
      });
      var body = $("transfer-body"); body.innerHTML = "";
      c.recent.forEach(function (t) {
        var d = new Date(t.created_at);
        var tr = document.createElement("tr");
        tr.innerHTML = "<td>" + d.toLocaleDateString("en-SG", { day: "numeric", month: "short" }) + " " + d.toLocaleTimeString("en-SG", { hour: "2-digit", minute: "2-digit" }) + "</td><td>" + esc(t.bin_id) + "</td><td class='r'>" + fmt(t.weight_kg, 1) + "</td>";
        body.appendChild(tr);
      });
    }).catch(function (e) { toast(e.message); });
  }

  // ---------- Init ----------
  Promise.all([api("/api/health"), api("/api/locations")]).then(function (r) {
    state.today = r[0].today;
    state.locations = r[1];
    state.locations.forEach(function (l) { l.stalls.forEach(function (s) { state.stalls[s.id] = s; }); });
    state.insightStall = Object.keys(state.stalls)[0];
    $("conn").textContent = "Connected · " + (r[0].claude_ready ? "Claude photo recognition on" : "photo recognition off (no Anthropic API key)");
    fillLocations(); fillStalls(); renderChips();
    var start = location.hash.slice(1);
    showTab(tabs.indexOf(start) >= 0 ? start : "bin");
  }).catch(function () {
    $("conn").textContent = "Cannot reach the server. Start it with: uv run uvicorn app.main:app";
    $("conn").classList.add("bad");
  });

  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () { if (state.tab === "insights") loadInsights(); });
  }
})();
