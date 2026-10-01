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
          var msg = typeof body.detail === "string" ? body.detail
            : Array.isArray(body.detail) ? body.detail.map(function (d) { return String(d.msg).replace(/^Value error, /, ""); }).join(" ")
            : "Request failed (" + res.status + ")";
          throw new Error(msg);
        }
        return body;
      });
    });
  }

  function currentLocation() { return state.locations.filter(function (l) { return l.id === $("sel-location").value; })[0]; }
  function currentBin() { return currentLocation().bins[0]; }

  // ---------- Tabs ----------
  var tabs = ["bin", "insights", "compost"];
  function showTab(name) {
    state.tab = name;
    tabs.forEach(function (t) {
      $("tab-" + t).setAttribute("aria-selected", t === name ? "true" : "false");
      $("view-" + t).hidden = t !== name;
    });
    if (name === "insights") { loadInsights(); loadMenu(); }
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
      var by = d.classified_by === "openai" ? "OpenAI " + Math.round(d.confidence * 100) + "%" : d.classified_by === "device" ? "Device label" : "–";
      var tr = document.createElement("tr");
      tr.className = "clickable"; tr.tabIndex = 0;
      tr.setAttribute("aria-label", "Show details for " + (d.dish || "unidentified item") + " at " + t.toLocaleTimeString("en-SG"));
      tr.addEventListener("click", function () { openDetail(d.id); });
      tr.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDetail(d.id); } });
      var counted = d.waste_kg == null ? d.weight_kg : d.waste_kg;
      var share = d.is_waste && d.edible_fraction < 1 ? " <span class='muted'>(" + Math.round(d.edible_fraction * 100) + "%)</span>" : "";
      tr.innerHTML = "<td class='num'>" + t.toLocaleTimeString("en-SG", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) + "</td>" +
        "<td>" + esc(state.stalls[d.stall_id].name) + "</td><td>" + esc(d.dish || "Unidentified") + "</td>" +
        "<td><span class='pill " + d.source + "'>" + (d.source === "plate" ? "Customer" : "Vendor") + "</span>" +
        (d.is_waste ? "" : " <span class='pill none' title='" + esc(d.waste_note) + "'>Not waste</span>") + "</td>" +
        "<td>" + by + "</td><td class='r'>" + fmt(d.weight_kg, 3) + "</td>" +
        "<td class='r" + (d.is_waste ? "" : " struck") + "'>" + fmt(counted, 3) + share + "</td>";
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

  // ---------- Live camera ----------
  var cam = { stream: null, freezeTimer: null };

  function cameraHint(msg, bad) {
    var h = $("camera-hint"); h.textContent = msg; h.classList.toggle("error", !!bad);
  }

  function listCameras(activeId) {
    return navigator.mediaDevices.enumerateDevices().then(function (devices) {
      var sel = $("sel-camera"); sel.innerHTML = "<option value=''>Camera off</option>";
      devices.filter(function (d) { return d.kind === "videoinput"; }).forEach(function (d, i) {
        var o = document.createElement("option");
        o.value = d.deviceId; o.textContent = d.label || "Camera " + (i + 1);
        sel.appendChild(o);
      });
      sel.value = activeId || "";
    });
  }

  function stopCamera() {
    if (cam.stream) cam.stream.getTracks().forEach(function (t) { t.stop(); });
    cam.stream = null;
    $("cam-video").hidden = true;
    $("btn-camera").textContent = "Turn on camera";
    $("sel-camera").value = "";
    cameraHint("Camera is off. Weigh-ins are saved without a photo unless you upload one.");
  }

  function startCamera(deviceId) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      cameraHint("This browser blocks the camera on this address. Open the app at http://localhost:8000 on the laptop, or use Upload a photo.", true);
      return Promise.resolve();
    }
    if (cam.stream) cam.stream.getTracks().forEach(function (t) { t.stop(); });
    var video = deviceId ? { deviceId: { exact: deviceId } } : { facingMode: "environment" };
    return navigator.mediaDevices.getUserMedia({ video: video, audio: false }).then(function (stream) {
      cam.stream = stream;
      var v = $("cam-video"); v.srcObject = stream; v.hidden = false;
      $("cam-photo").hidden = true;
      $("btn-camera").textContent = "Turn off camera";
      $("cam-dish").textContent = "Camera live"; $("cam-conf").textContent = "–";
      cameraHint("Camera on. Each weigh-in takes a photo for dish recognition.");
      var track = stream.getVideoTracks()[0];
      return listCameras(track.getSettings().deviceId);
    }).catch(function (e) {
      cam.stream = null;
      var msg = e.name === "NotAllowedError" ? "Camera permission was denied. Allow it in the browser's address bar, then press Turn on camera."
        : e.name === "NotFoundError" ? "No camera found. Plug one in or use Upload a photo."
        : e.name === "NotReadableError" ? "The camera is in use by another app. Close it and try again."
        : "Could not start the camera: " + e.message;
      cameraHint(msg, true);
    });
  }

  function captureFrame() {
    var v = $("cam-video");
    if (!cam.stream || !v.videoWidth) return Promise.resolve(null);
    var scale = Math.min(1, 1024 / v.videoWidth);
    var c = document.createElement("canvas");
    c.width = Math.round(v.videoWidth * scale); c.height = Math.round(v.videoHeight * scale);
    c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
    return new Promise(function (resolve) {
      c.toBlob(function (blob) {
        resolve(blob ? new File([blob], "bin-camera.jpg", { type: "image/jpeg" }) : null);
      }, "image/jpeg", 0.85);
    });
  }

  $("btn-camera").addEventListener("click", function () { if (cam.stream) stopCamera(); else startCamera(); });
  $("sel-camera").addEventListener("change", function () {
    if ($("sel-camera").value) startCamera($("sel-camera").value); else stopCamera();
  });

  // ---------- Weigh-in details ----------
  function factRow(label, value) {
    return "<div><dt>" + label + "</dt><dd>" + value + "</dd></div>";
  }

  function openDetail(id) {
    var dlg = $("detail");
    $("detail-title").textContent = "Loading…";
    $("detail-body").innerHTML = "";
    if (!dlg.open) dlg.showModal();
    api("/api/drops/" + id).then(function (d) {
      var t = new Date(d.created_at);
      var counted = d.waste_kg == null ? d.weight_kg : d.waste_kg;
      $("detail-title").textContent = (d.dish || "Unidentified") + " · " + d.stall_name;
      var by = d.classified_by === "openai" ? "OpenAI vision" : d.classified_by === "device" ? "Label sent with the weigh-in" : d.classified_by === "seed" ? "Demo history" : "Not identified";
      var html = "";
      if (d.image_url) html += '<img class="detail-photo" src="' + d.image_url + '" alt="Photo taken by the bin camera">';
      html += '<dl class="facts">' +
        factRow("Time", t.toLocaleString("en-SG", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" })) +
        factRow("Source", d.source === "plate" ? "Customer plate" : "Vendor, end of day") +
        factRow("Weighed", fmt(d.weight_kg, 3) + " kg") +
        factRow("Edible share", d.is_waste ? Math.round(d.edible_fraction * 100) + "%" : "0% (not food waste)") +
        factRow("Counted as food waste", "<b>" + fmt(counted, 3) + " kg</b>") +
        factRow("Dish confidence", d.confidence == null ? "–" : Math.round(d.confidence * 100) + "%") +
        factRow("Identified by", by) +
        factRow("Model", d.model ? esc(d.model) : "–") +
        "</dl>";
      if (d.ingredients && d.ingredients.length) {
        html += "<h3>Food waste by ingredient</h3><table><tbody>" + d.ingredients.map(function (p) {
          return "<tr><td>" + esc(p.ingredient) + "</td><td class='r'>" + Math.round(p.share * 100) + "%</td><td class='r'>" + fmt(p.waste_kg, 3) + " kg</td></tr>";
        }).join("") + "</tbody></table>";
      }
      if (d.classified_by !== "openai") {
        html += '<p class="note">No photo was analysed for this weigh-in, so the full weight counts as food waste' +
          (d.dish ? ", split by the " + esc(d.dish) + " recipe." : " and the ingredients are unknown.") + '</p>';
      } else {
        html += "<h3>What the model saw</h3><p>" + esc(d.waste_note) + "</p>";
        html += "<h3>Model's reasoning</h3><p class='prewrap'>" + esc(d.model_reasoning) + "</p>";
        var pretty = d.model_output;
        try { pretty = JSON.stringify(JSON.parse(d.model_output), null, 2); } catch (e) {}
        html += "<h3>Raw model output</h3><pre>" + esc(pretty) + "</pre>";
        html += "<details><summary>Prompt sent to the model</summary><pre>" + esc(d.model_prompt) + "</pre></details>";
      }
      $("detail-body").innerHTML = html;
    }).catch(function (e) {
      $("detail-title").textContent = "Could not load this weigh-in";
      $("detail-body").innerHTML = '<p class="error">' + esc(e.message) + "</p>";
    });
  }
  $("detail-close").addEventListener("click", function () { $("detail").close(); });
  $("detail").addEventListener("click", function (e) { if (e.target === $("detail")) $("detail").close(); });
  $("btn-last-detail").addEventListener("click", function () { if (state.lastDropId) openDetail(state.lastDropId); });

  function showResult(res, photo) {
    var d = res.drop;
    state.lastDropId = d.id;
    $("btn-last-detail").hidden = d.classified_by !== "openai";
    var stall = state.stalls[d.stall_id];
    $("cam-dish").textContent = !d.is_waste
      ? "No food waste · 0 kg counted"
      : (d.dish || "Unidentified") + " · " + Math.round(d.edible_fraction * 100) + "% edible · " + fmt(d.waste_kg == null ? d.weight_kg : d.waste_kg, 3) + " kg counted";
    $("cam-conf").textContent = d.classified_by === "openai" ? Math.round(d.confidence * 100) + "% · OpenAI"
      : d.classified_by === "device" ? "Device label" : photo ? "Not identified" : "No photo";
    var img = $("cam-photo");
    clearTimeout(cam.freezeTimer);
    if (d.image_url) {
      img.src = d.image_url; img.hidden = false;
      // Hold the captured frame briefly, then go back to the live feed.
      if (cam.stream) cam.freezeTimer = setTimeout(function () { img.hidden = true; }, 3000);
    } else {
      img.hidden = true;
      if (!cam.stream) drawCam(0, { kg: d.weight_kg });
    }
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
    var upload = $("in-photo").files[0] || null;
    var photo = null;
    setBusy(true);
    (upload ? Promise.resolve(upload) : captureFrame())
      .then(function (p) {
        photo = p;
        $("cam").classList.add("scanning");
        $("unit-status").textContent = photo ? "Identifying" : "Weighing";
        $("cam-dish").textContent = photo ? "Identifying…" : "Weighing…";
        $("cam-conf").textContent = "–";
        $("lcd-weight").textContent = "0.000";
        return postDrop($("sel-stall").value, selectedSource(), weight, $("sel-dish").value, photo);
      })
      .then(function (res) {
        $("cam").classList.remove("scanning");
        showResult(res, photo);
        $("unit-status").textContent = res.drop.is_waste ? "Saved" : "Saved · not counted";
        $("in-weight").value = ""; $("in-photo").value = "";
        if (res.recognition_error) {
          $("cam-conf").textContent = "Not identified";
          err.textContent = "Weigh-in saved, but the dish was not identified. " + res.recognition_error;
          err.hidden = false;
        }
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
  var SERIES = 6; // categorical slots; more ingredients fold into the grey "other" colour

  function ingColor(order, name) {
    var i = order.indexOf(name);
    if (name === "Unidentified" || i < 0 || i >= SERIES) return "var(--s-other)";
    return "var(--s" + (i + 1) + ")";
  }
  function swatch(order, name) {
    return '<i class="swatch" style="background:' + ingColor(order, name) + '"></i>';
  }
  function kg(n, d) { return fmt(n, d == null ? 1 : d) + " kg"; }

  function renderChips() {
    var chips = $("stall-chips"); chips.innerHTML = "";
    Object.keys(state.stalls).forEach(function (id) {
      var b = document.createElement("button");
      b.type = "button"; b.textContent = state.stalls[id].name;
      b.setAttribute("aria-pressed", id === state.insightStall ? "true" : "false");
      b.addEventListener("click", function () {
        if (state.menuEditing && !leaveEditor()) return;
        state.insightStall = id; state.insightsKey = null; renderChips(); loadInsights(); loadMenu();
      });
      chips.appendChild(b);
    });
  }

  function kpi(label, value, unit, cls) {
    return '<div class="kpi ' + cls + '"><span class="label">' + label + '</span><span class="v">' + value + '<small>' + unit + '</small></span></div>';
  }

  function renderChart(stall, days, order) {
    var W = 720, H = 280, L = 44, R = 12, T = 14, B = 40;
    var max = Math.max.apply(null, days.map(function (d) { return d.unsold_kg; }).concat([1]));
    var steps = [0.5, 1, 2, 5, 10, 20, 50], step = steps.filter(function (s) { return max / s <= 6; })[0] || 100;
    var top = Math.ceil(max / step) * step;
    var y = function (v) { return T + (H - T - B) * (1 - v / top); };
    var bw = (W - L - R) / days.length;
    var ink = cssVar("--ink"), muted = cssVar("--muted"), line = cssVar("--line"), surface = cssVar("--surface");
    var out = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Cooked kilograms thrown away at closing per day for ' + esc(stall.name) + ', split by ingredient">';
    for (var v = 0; v <= top + 1e-9; v += step) {
      out += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v) + '" y2="' + y(v) + '" stroke="' + line + '"/>';
      out += '<text x="' + (L - 8) + '" y="' + (y(v) + 4) + '" text-anchor="end" font-size="11" fill="' + muted + '" font-family="JetBrains Mono, monospace">' + (+v.toFixed(1)) + '</text>';
    }
    days.forEach(function (d, i) {
      var x = L + i * bw + bw * 0.18, w = bw * 0.64, base = 0;
      var date = new Date(d.day + "T00:00:00");
      var names = order.filter(function (n) { return d.unsold[n]; });
      names.forEach(function (n) {
        var val = d.unsold[n];
        // 1px surface stroke on each side gives the 2px gap between stacked segments.
        out += '<rect x="' + x + '" y="' + y(base + val) + '" width="' + w + '" height="' + Math.max(0, y(base) - y(base + val)) + '" fill="' + ingColor(order, n) + '"' +
          (d.partial ? ' fill-opacity="0.55"' : '') + ' stroke="' + surface + '" stroke-width="1"><title>' +
          esc(n) + ': ' + fmt(val, 2) + ' kg cooked' + (d.partial ? ' (today so far)' : '') + '</title></rect>';
        base += val;
      });
      if (d.partial) {
        out += '<rect x="' + x + '" y="' + y(Math.max(base, 0)) + '" width="' + w + '" height="' + (y(0) - y(base)) + '" fill="none" stroke="' + ink + '" stroke-width="1.5" stroke-dasharray="4 3"/>';
        if (!base) out += '<text x="' + (x + w / 2) + '" y="' + (y(0) - 6) + '" text-anchor="middle" font-size="10" fill="' + muted + '" font-family="Public Sans, sans-serif">none yet</text>';
      }
      out += '<text x="' + (x + w / 2) + '" y="' + (H - B + 16) + '" text-anchor="middle" font-size="11"' + (d.partial ? ' font-weight="700"' : '') +
        ' fill="' + (d.weekend && !d.partial ? muted : ink) + '" font-family="Public Sans, sans-serif">' + (d.partial ? "Today" : date.toLocaleDateString("en-SG", { weekday: "short" })) + '</text>';
      out += '<text x="' + (x + w / 2) + '" y="' + (H - B + 30) + '" text-anchor="middle" font-size="10" fill="' + muted + '" font-family="JetBrains Mono, monospace">' + date.getDate() + '/' + (date.getMonth() + 1) + '</text>';
    });
    $("chart").innerHTML = out + "</svg>";
    var seen = order.filter(function (n) { return days.some(function (d) { return d.unsold[n]; }); });
    $("chart-legend").innerHTML = seen.map(function (n) { return "<span>" + swatch(order, n) + esc(n) + "</span>"; }).join("") +
      '<span><i class="today-swatch"></i>Today, still in progress (not used for advice)</span>';
  }

  function renderCook(rows, order, weekdays) {
    $("cook-intro").textContent = "Average leftover at closing over " + weekdays + " weekdays, minus a buffer of half a standard deviation so the stall rarely runs out.";
    if (!rows.length) { $("cook-table").innerHTML = '<p class="empty">Needs at least 3 weekdays of closing weigh-ins.</p>'; return; }
    $("cook-table").innerHTML = '<table><thead><tr><th>Ingredient</th><th class="r">Thrown away / weekday</th><th class="r">Cook less, raw</th><th class="r">Cook less, cooked</th><th class="r">Saves / day</th></tr></thead><tbody>' +
      rows.map(function (r) {
        return "<tr><td>" + swatch(order, r.ingredient) + esc(r.ingredient) + "</td>" +
          "<td class='r'>" + kg(r.avg_unsold_cooked_kg) + " cooked</td>" +
          "<td class='r'><b>" + kg(r.cut_raw_kg) + "</b></td>" +
          "<td class='r'>" + kg(r.cut_cooked_kg) + "</td>" +
          "<td class='r'>" + money2(r.sgd_per_day) + "</td></tr>";
      }).join("") + "</tbody></table>";
  }

  function renderServe(rows, order) {
    if (!rows.length) { $("serve-table").innerHTML = '<p class="empty">No serving is being left behind much. Needs at least 5 weekday plates of a dish.</p>'; return; }
    $("serve-table").innerHTML = '<table><thead><tr><th>Dish · ingredient</th><th class="r">Left / plate</th><th class="r">Serving now → suggested</th><th class="r">Saves / day</th></tr></thead><tbody>' +
      rows.slice(0, 8).map(function (r) {
        return "<tr><td>" + swatch(order, r.ingredient) + esc(r.ingredient) + " <span class='muted'>in " + esc(r.dish) + "</span></td>" +
          "<td class='r'>" + r.avg_left_g + " g <span class='muted'>(" + r.left_pct + "%)</span></td>" +
          "<td class='r'>" + r.serving_g + " → <b>" + r.new_serving_g + " g</b></td>" +
          "<td class='r'>" + kg(r.cut_raw_kg_per_day, 2) + " raw · " + money2(r.sgd_per_day) + "</td></tr>";
      }).join("") + "</tbody></table>";
  }

  function money2(n) { return "S$" + Number(n).toFixed(2); }

  function loadInsights(quiet) {
    if (!state.insightStall) return Promise.resolve();
    var stallId = state.insightStall;
    return api("/api/stalls/" + stallId + "/insights").then(function (data) {
      if (stallId !== state.insightStall) return; // the user switched stall while this was loading
      $("insights-updated").textContent = "Updated " + new Date().toLocaleTimeString("en-SG", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      // Polling: skip the redraw when nothing changed, so the page doesn't flicker.
      var key = JSON.stringify(data);
      if (quiet && key === state.insightsKey) return;
      state.insightsKey = key;
      var s = data.stall, order = data.ingredient_order, t = data.today, tot = data.totals;
      var past = data.days.filter(function (d) { return !d.partial && !d.weekend; });
      var avgUnsold = past.length ? past.reduce(function (a, d) { return a + d.unsold_kg; }, 0) / past.length : 0;
      var avgPlate = past.length ? past.reduce(function (a, d) { return a + d.plate_kg; }, 0) / past.length : 0;
      $("kpis").innerHTML =
        kpi("Thrown away at closing", fmt(avgUnsold, 1), "kg cooked / weekday", "warn") +
        kpi("Left on plates", fmt(avgPlate, 1), "kg / weekday", "") +
        kpi("Can cook less", fmt(tot.cut_raw_kg_per_day, 1), "kg raw / day", "hl") +
        kpi("Could save", money(tot.sgd_per_month), "per month", "hl");
      $("example-menu-note").hidden = !data.menu_is_example;
      renderChart(s, data.days, order);
      renderCook(data.cook_less, order, data.weekdays_used);
      renderServe(data.serve_less, order);
      var demo = data.days.filter(function (d) { return d.demo; });
      $("demo-note").textContent = demo.length
        ? demo.length + " of the earlier days (" + shortDate(demo[0].day) + " to " + shortDate(demo[demo.length - 1].day) + ") are generated demo data."
        : "All days shown are real data.";
      var names = order.filter(function (n) { return t.unsold[n]; });
      $("today").innerHTML = '<table><tbody>' +
        '<tr><td>Items weighed</td><td class="r">' + t.drops + '</td></tr>' +
        '<tr><td>Not counted (no food waste in photo)</td><td class="r">' + t.not_waste_drops + '</td></tr>' +
        '<tr><td>Left on customer plates</td><td class="r">' + kg(t.plate_kg, 2) + '</td></tr>' +
        '<tr><td>Thrown away by vendor</td><td class="r">' + kg(t.unsold_kg, 2) + '</td></tr>' +
        names.map(function (n) { return '<tr><td class="indent">' + swatch(order, n) + esc(n) + '</td><td class="r">' + kg(t.unsold[n], 2) + '</td></tr>'; }).join("") +
        '</tbody></table>';
    }).catch(function (e) {
      if (quiet) $("insights-updated").textContent = "Cannot reach the server";
      else toast(e.message);
    });
  }

  function shortDate(iso) { return new Date(iso + "T00:00:00").toLocaleDateString("en-SG", { day: "numeric", month: "short" }); }

  // Refresh the open insights tab every 5 seconds so new weigh-ins show up during a demo.
  setInterval(function () {
    if (state.tab === "insights" && !document.hidden) loadInsights(true);
  }, 5000);
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden && state.tab === "insights") loadInsights(true);
  });

  $("btn-reset-demo").addEventListener("click", function () {
    if (!window.confirm("Replace the demo history with a fresh 14 days ending yesterday? Real weigh-ins are kept.")) return;
    var btn = $("btn-reset-demo"); btn.disabled = true;
    api("/api/demo/reset", { method: "POST" })
      .then(function () { toast("Demo data reset"); state.insightsKey = null; return loadInsights(); })
      .catch(function (e) { toast(e.message); })
      .finally(function () { btn.disabled = false; });
  });

  // ---------- Menu ----------
  function loadMenu() {
    var stallId = state.insightStall;
    $("menu-title").textContent = "Menu · " + state.stalls[stallId].name;
    return api("/api/stalls/" + stallId + "/menu").then(function (m) {
      if (stallId !== state.insightStall) return;
      state.menu = m;
      if (!state.menuEditing) { $("menu-status").textContent = m.is_example ? "Example menu with made-up recipes." : "Saved menu."; renderMenuView(m); }
    }).catch(function (e) { toast(e.message); });
  }

  function renderMenuView(m) {
    var ing = {}; m.ingredients.forEach(function (i) { ing[i.name] = i; });
    $("menu-view").innerHTML = '<div class="menu-items">' + m.items.map(function (item) {
      var total = item.recipe.reduce(function (a, l) { return a + l.grams; }, 0);
      return '<div class="menu-item"><h4>' + esc(item.name) + ' <span class="muted">' + Math.round(total) + ' g</span></h4><ul>' +
        item.recipe.map(function (l) {
          var i = ing[l.ingredient] || {};
          return "<li><span>" + esc(l.ingredient) + "</span><span class='num'>" + l.grams + " g cooked · " + fmt(l.grams / (i.cooked_per_raw || 1), 0) + " g raw</span></li>";
        }).join("") + "</ul></div>";
    }).join("") + "</div>";
  }

  function ingredientRow(i) {
    var tr = document.createElement("tr");
    tr.innerHTML = '<td><input type="text" class="ing-name" aria-label="Ingredient name" maxlength="60" value="' + esc(i.name) + '"></td>' +
      '<td><input type="number" class="ing-ratio" aria-label="Cooked weight divided by raw weight" min="0.05" max="10" step="0.05" value="' + i.cooked_per_raw + '"></td>' +
      '<td><input type="number" class="ing-cost" aria-label="Cost in S$ per raw kg" min="0" max="500" step="0.1" value="' + i.cost_per_raw_kg + '"></td>' +
      '<td><button class="btn ghost small" type="button" aria-label="Remove ingredient">Remove</button></td>';
    tr.querySelector("button").addEventListener("click", function () { tr.remove(); });
    return tr;
  }

  function recipeRow(l) {
    var row = document.createElement("div");
    row.className = "recipe-row";
    row.innerHTML = '<input type="text" class="line-ing" aria-label="Ingredient" list="ingredient-names" value="' + esc(l.ingredient) + '">' +
      '<input type="number" class="line-g" aria-label="Cooked grams per portion" min="1" max="2000" step="5" value="' + l.grams + '"><span class="hint">g</span>' +
      '<button class="btn ghost small" type="button" aria-label="Remove ingredient from this item">Remove</button>';
    row.querySelector("button").addEventListener("click", function () { row.remove(); });
    return row;
  }

  function itemBlock(item) {
    var div = document.createElement("div");
    div.className = "edit-item";
    div.innerHTML = '<div class="inline"><input type="text" class="item-name" aria-label="Menu item name" maxlength="80" value="' + esc(item.name) + '">' +
      '<button class="btn ghost small" type="button">Remove item</button></div><div class="recipe"></div>' +
      '<button class="btn ghost small add-line" type="button">Add ingredient to this item</button>';
    var lines = div.querySelector(".recipe");
    item.recipe.forEach(function (l) { lines.appendChild(recipeRow(l)); });
    div.querySelector(".inline button").addEventListener("click", function () { div.remove(); });
    div.querySelector(".add-line").addEventListener("click", function () { lines.appendChild(recipeRow({ ingredient: "", grams: 100 })); });
    return div;
  }

  function openEditor(m, status) {
    state.menuEditing = true;
    $("menu-view").hidden = true; $("menu-editor").hidden = false; $("menu-error").hidden = true;
    $("btn-menu-edit").disabled = true;
    $("menu-status").textContent = status;
    var tb = $("edit-ingredients"); tb.innerHTML = "";
    m.ingredients.forEach(function (i) { tb.appendChild(ingredientRow(i)); });
    var items = $("edit-items"); items.innerHTML = "";
    m.items.forEach(function (it) { items.appendChild(itemBlock(it)); });
    refreshIngredientList();
  }

  function closeEditor() {
    state.menuEditing = false;
    $("menu-view").hidden = false; $("menu-editor").hidden = true; $("btn-menu-edit").disabled = false;
    loadMenu();
  }
  function leaveEditor() {
    if (!window.confirm("Discard your unsaved menu changes?")) return false;
    closeEditor(); return true;
  }

  // Suggest existing ingredient names while typing a recipe line.
  function refreshIngredientList() {
    var dl = $("ingredient-names");
    if (!dl) { dl = document.createElement("datalist"); dl.id = "ingredient-names"; document.body.appendChild(dl); }
    dl.innerHTML = Array.prototype.map.call(document.querySelectorAll("#edit-ingredients .ing-name"), function (i) {
      return '<option value="' + esc(i.value) + '">';
    }).join("");
  }
  $("edit-ingredients").addEventListener("input", refreshIngredientList);

  function readEditor() {
    return {
      ingredients: Array.prototype.map.call(document.querySelectorAll("#edit-ingredients tr"), function (tr) {
        return { name: tr.querySelector(".ing-name").value.trim(), cooked_per_raw: parseFloat(tr.querySelector(".ing-ratio").value), cost_per_raw_kg: parseFloat(tr.querySelector(".ing-cost").value) || 0 };
      }),
      items: Array.prototype.map.call(document.querySelectorAll("#edit-items .edit-item"), function (div) {
        return {
          name: div.querySelector(".item-name").value.trim(),
          recipe: Array.prototype.map.call(div.querySelectorAll(".recipe-row"), function (r) {
            return { ingredient: r.querySelector(".line-ing").value.trim(), grams: parseFloat(r.querySelector(".line-g").value) };
          })
        };
      })
    };
  }

  $("btn-menu-edit").addEventListener("click", function () { if (state.menu) openEditor(state.menu, "Editing the menu. Changes apply to new weigh-ins; past weigh-ins keep their ingredients."); });
  $("btn-menu-cancel").addEventListener("click", function () { leaveEditor(); });
  $("btn-add-ingredient").addEventListener("click", function () { $("edit-ingredients").appendChild(ingredientRow({ name: "", cooked_per_raw: 1, cost_per_raw_kg: 0 })); });
  $("btn-add-item").addEventListener("click", function () { $("edit-items").appendChild(itemBlock({ name: "", recipe: [{ ingredient: "", grams: 100 }] })); });

  $("menu-editor").addEventListener("submit", function (e) {
    e.preventDefault();
    var err = $("menu-error"); err.hidden = true;
    api("/api/stalls/" + state.insightStall + "/menu", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(readEditor()) })
      .then(function (m) {
        state.stalls[state.insightStall].menu = m.items.map(function (i) { return i.name; });
        if ($("sel-stall").value === state.insightStall) fillDishes();
        toast("Menu saved"); closeEditor(); state.insightsKey = null; loadInsights();
      })
      .catch(function (e) { err.textContent = e.message; err.hidden = false; });
  });

  $("in-menu-photo").addEventListener("change", function () {
    var file = $("in-menu-photo").files[0];
    if (!file) return;
    if (state.menuEditing && !leaveEditor()) { $("in-menu-photo").value = ""; return; }
    var fd = new FormData(); fd.append("image", file);
    $("menu-status").textContent = "Reading the menu photo. This can take up to a minute…";
    api("/api/stalls/" + state.insightStall + "/menu/scan", { method: "POST", body: fd })
      .then(function (draft) {
        if (!draft.items.length) { $("menu-status").textContent = "No dishes found. " + (draft.notes || "Try a sharper photo of the menu."); return; }
        openEditor(draft, "Draft read by " + draft.model + " from your photo. Weights and prices are estimates: check them, then save. " + (draft.notes || ""));
      })
      .catch(function (e) { $("menu-status").textContent = e.message; })
      .finally(function () { $("in-menu-photo").value = ""; });
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
    $("conn").textContent = "Connected · " + (r[0].vision_ready ? "OpenAI photo recognition on" : "photo recognition off (set OPENAI_API_KEY)");
    fillLocations(); fillStalls(); renderChips();
    startCamera();
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
