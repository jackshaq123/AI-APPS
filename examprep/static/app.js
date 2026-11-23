// Quiz, flashcards, lead capture and checkout tracking. No build step, no libraries.
(function () {
  "use strict";
  var csrf = document.querySelector('meta[name="csrf-token"]').content;

  function track(event, params) {
    if (window.fbq) window.fbq("track", event, params || {});
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify(body),
      credentials: "same-origin",
    });
  }

  function fill(template, values) {
    return template.replace(/\{(\w+)\}/g, function (_, k) {
      return values[k] !== undefined ? values[k] : "";
    });
  }

  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // ---- checkout buttons ----
  document.querySelectorAll("form[data-checkout]").forEach(function (form) {
    form.addEventListener("submit", function () { track("InitiateCheckout"); });
  });

  // ---- quiz (free, practice, mock) ----
  var root = document.getElementById("quiz");
  if (root && document.getElementById("quiz-data")) {
    var questions = JSON.parse(document.getElementById("quiz-data").textContent);
    var text = JSON.parse(document.getElementById("quiz-text").textContent);
    var mode = root.dataset.mode;
    var slug = root.dataset.slug;
    var isMock = mode === "mock" || mode === "mock65";
    var paid = mode !== "free";
    var i = 0, score = 0, missed = [];

    function render() {
      root.innerHTML = "";
      var q = questions[i];
      root.appendChild(el("p", { class: "quiet" }, fill(text.question_of, { i: i + 1, n: questions.length })));
      root.appendChild(el("h2", { class: "q" }, q.q));
      var list = el("div", { class: "options" });
      q.options.forEach(function (opt, idx) {
        var b = el("button", { class: "option", type: "button" }, opt);
        b.addEventListener("click", function () { answer(idx, list); });
        list.appendChild(b);
      });
      root.appendChild(list);
    }

    function answer(idx, list) {
      var q = questions[i];
      var right = idx === q.correct_index;
      if (right) score++; else missed.push(q);
      if (paid) post("/api/" + slug + "/progress", { question_id: q.id, correct: right });

      var buttons = list.querySelectorAll("button");
      buttons.forEach(function (b, n) {
        b.disabled = true;
        if (!isMock && n === q.correct_index) b.classList.add("right");
        if (!isMock && n === idx && !right) b.classList.add("wrong");
      });
      // Mock tests behave like the real thing: no feedback until the end.
      if (!isMock) {
        root.appendChild(el("p", { class: right ? "ok" : "bad" }, right ? text.correct : text.wrong));
        if (q.answers.length > 1) {
          root.appendChild(el("p", { class: "quiet" }, text.accepted + ": " + q.answers.join(" · ")));
        }
        if (q.changes) root.appendChild(el("p", { class: "note" }, text.change_note));
      }
      var last = i === questions.length - 1;
      var next = el("button", { class: "btn", type: "button" }, last ? text.finish : text.next);
      next.addEventListener("click", function () {
        if (last) finish(); else { i++; render(); }
      });
      if (isMock) { next.click(); } else { root.appendChild(next); next.focus(); }
    }

    function showReview() {
      var review = document.getElementById("review");
      if (!missed.length) return;
      review.hidden = false;
      review.innerHTML = "";
      missed.forEach(function (q) {
        var card = el("article", { class: "card" });
        card.appendChild(el("p", { class: "q" }, q.q));
        card.appendChild(el("p", {}, q.answers.join(" · ")));
        review.appendChild(card);
      });
    }

    function finish() {
      var n = questions.length;
      if (mode === "free") {
        root.hidden = true;
        var after = document.getElementById("after-free");
        after.hidden = false;
        after.querySelector("[data-score]").textContent = fill(text.your_score, { score: score, n: n });
        showReview();
        return;
      }
      root.innerHTML = "";
      if (isMock) {
        var passMark = parseInt(root.dataset.passMark, 10);
        var passed = score >= passMark;
        root.appendChild(el("h2", { class: passed ? "ok" : "bad" },
          fill(passed ? text.passed : text.failed, { score: score, n: n, pass_mark: passMark })));
        post("/api/" + slug + "/mock-result", { score: score, total: n, pass_mark: passMark });
      } else {
        root.appendChild(el("h2", {}, fill(text.your_score, { score: score, n: n })));
      }
      var again = el("a", { class: "btn", href: location.pathname + location.search }, text.try_again);
      root.appendChild(again);
      showReview();
    }

    if (questions.length) render();
  }

  // ---- lead form after the free quiz ----
  var leadForm = document.getElementById("lead-form");
  if (leadForm) {
    leadForm.addEventListener("submit", function (e) {
      e.preventDefault();
      var slug = document.getElementById("quiz").dataset.slug;
      var email = leadForm.email.value;
      post("/exam/" + slug + "/lead", { email: email }).then(function (r) {
        if (!r.ok) { leadForm.email.focus(); return; }
        track("Lead");
        leadForm.hidden = true;
        document.getElementById("upsell").hidden = false;
      });
    });
  }

  // ---- flashcards ----
  var cards = document.getElementById("cards");
  if (cards) {
    var cardSlug = cards.dataset.slug;
    cards.addEventListener("click", function (e) {
      var card = e.target.closest(".flash");
      if (!card) return;
      if (e.target.matches("[data-reveal]")) {
        card.querySelector(".a").hidden = false;
        e.target.hidden = true;
      } else if (e.target.matches("[data-mark]")) {
        post("/api/" + cardSlug + "/progress", { question_id: card.dataset.qid, correct: e.target.dataset.mark === "1" });
        card.classList.add(e.target.dataset.mark === "1" ? "done-ok" : "done-bad");
        card.querySelectorAll("[data-mark]").forEach(function (b) { b.disabled = true; });
      }
    });
  }
})();
