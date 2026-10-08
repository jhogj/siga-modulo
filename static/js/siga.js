// SIGA · Radar RJ — menus de filtro, auto-envio, URL limpa. Sem dependências.
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var MENU = "details[data-menu]";
  var desktop = window.matchMedia("(min-width: 641px)").matches;

  function enviar(f) { if (f.requestSubmit) f.requestSubmit(); else f.submit(); }
  function semAcento(s) { return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }
  function fechar(exceto) { $$(MENU + "[open]").forEach(function (d) { if (d !== exceto) d.open = false; }); }

  // Texto do botão do menu conforme a opção marcada (e as datas, no período livre)
  function resumo(d) {
    var r = $("input[type=radio]:checked", d), botao = $(".seletor__botao", d), texto = $(".seletor__texto", d);
    var rotulo = botao.getAttribute("data-rotulo"), valor = r ? r.value : "";
    var t = rotulo, titulo = "";
    if (r && r.hasAttribute("data-personalizado")) {
      var de = $("input[name=de]", d).value, ate = $("input[name=ate]", d).value;
      t = de && ate ? de + " a " + ate : de ? "A partir de " + de : ate ? "Até " + ate : rotulo;
      if (!de && !ate) valor = "";
    } else if (valor) {
      t = r.getAttribute("data-resumo") || rotulo;
      titulo = r.getAttribute("data-titulo") || "";
    }
    texto.textContent = t;
    if (titulo) botao.title = titulo; else botao.removeAttribute("title");
    d.classList.toggle("seletor--ativo", !!valor);
  }

  // Abrir um fecha os outros; o campo de busca do menu recebe foco no desktop
  document.addEventListener("toggle", function (e) {
    var d = e.target;
    if (!d.matches || !d.matches(MENU) || !d.open) return;
    fechar(d);
    var busca = $("[data-filtrar]", d);
    if (busca && desktop) busca.focus();
  }, true);
  document.addEventListener("click", function (e) {
    var s = e.target.closest(".seletor__botao");
    if (s && s.parentNode.classList.contains("seletor--desabilitado")) { e.preventDefault(); return; }
    if (!e.target.closest(MENU)) fechar();
    var aplicar = e.target.closest("[data-aplicar]");
    if (aplicar && aplicar.type === "button") { var d = aplicar.closest(MENU); resumo(d); d.open = false; }
  });
  document.addEventListener("keydown", function (e) {
    // Enter na busca do menu não envia o form: com uma única opção visível, escolhe ela
    if (e.key === "Enter" && e.target.matches("[data-filtrar]")) {
      e.preventDefault();
      var visiveis = $$(".seletor__opcoes .opcao:not([hidden]) input", e.target.closest(MENU));
      if (visiveis.length === 1) { visiveis[0].checked = true; visiveis[0].dispatchEvent(new Event("change", { bubbles: true })); }
      return;
    }
    if (e.key !== "Escape") return;
    var d = $(MENU + "[open]");
    if (d) { d.open = false; $(".seletor__botao", d).focus(); }
  });

  document.addEventListener("input", function (e) {
    var el = e.target;
    // Filtra a lista do menu (órgão) pelo texto, sem acento
    if (el.matches("[data-filtrar]")) {
      var termo = semAcento(el.value.trim()), d = el.closest(MENU), vistos = 0;
      $$(".seletor__opcoes .opcao", d).forEach(function (o) {
        var vazio = $("input", o).value === "";
        var ok = !termo || (!vazio && semAcento(o.textContent).indexOf(termo) >= 0);
        o.hidden = !ok;
        if (ok) vistos++;
      });
      var nada = $(".seletor__nada", d);
      if (nada) nada.hidden = vistos > 0;
    }
    // Máscara dd/mm/aaaa; digitar uma data marca "Outro período"
    if (el.matches("[data-data]")) {
      var n = el.value.replace(/\D/g, "").slice(0, 8);
      el.value = n.length > 4 ? n.slice(0, 2) + "/" + n.slice(2, 4) + "/" + n.slice(4)
        : n.length > 2 ? n.slice(0, 2) + "/" + n.slice(2) : n;
      var p = $("[data-personalizado]", el.closest(MENU));
      if (p) p.checked = true;
    }
  });

  // Escolher uma opção: atualiza o botão, fecha e (nos resultados) envia
  document.addEventListener("change", function (e) {
    var el = e.target, d = el.closest(MENU);
    if (!d || el.type !== "radio") return;
    if (el.hasAttribute("data-personalizado")) { $("input[name=de]", d).focus(); return; }
    $$("[data-data]", d).forEach(function (c) { c.value = ""; });
    resumo(d);
    d.open = false;
    if (el.form && el.form.hasAttribute("data-autoenvio")) enviar(el.form);
    if (el.name === "tipo") aplicarTipo();
  });

  // URL limpa: campos vazios não vão para a query string
  document.addEventListener("submit", function (e) {
    var f = e.target;
    if (!f.hasAttribute("data-limpar-vazios")) return;
    $$("input, select", f).forEach(function (c) {
      var vazio = c.value === "" && (c.type !== "radio" || c.checked);  // radio desmarcado já não vai
      if (c.name && vazio && !c.disabled) { c.disabled = true; c.setAttribute("data-vazio", ""); }
    });
    var p = $("[data-personalizado]:checked", f);  // datas livres vão como de/ate, sem "periodo"
    if (p && !p.disabled) { p.disabled = true; p.setAttribute("data-vazio", ""); }
  });

  // Home: período e órgão não valem para fornecedores e itens
  function aplicarTipo() {
    var tipo = $(".home__form input[name=tipo]:checked");
    if (!tipo) return;
    var sem = tipo.value === "fornecedores" || tipo.value === "itens";
    ["periodo", "orgao"].forEach(function (nome) {
      var c = $(".home__form input[name=" + nome + "]");
      var d = c && c.closest(MENU);
      if (!d) return;
      d.classList.toggle("seletor--desabilitado", sem);
      $$("input", d).forEach(function (i) { if (!i.matches("[data-filtrar]")) i.disabled = sem; });
      if (sem) d.open = false;
    });
  }
  var home = $(".home__form");
  if (home) home.addEventListener("reset", function () {
    setTimeout(function () { $$(MENU, home).forEach(resumo); aplicarTipo(); }, 0);
  });
  window.addEventListener("pageshow", function () {  // volta pelo histórico: reabilita o que o submit desligou
    $$("[data-vazio]").forEach(function (c) { c.disabled = false; c.removeAttribute("data-vazio"); });
    aplicarTipo();
  });
  aplicarTipo();

  // Home: foco no campo só no desktop. Abas que rolam: centraliza a ativa.
  if (home && $("#q") && desktop) $("#q").focus();
  $$(".abas [aria-current]").forEach(function (a) {
    var n = a.parentNode;
    n.scrollLeft += a.getBoundingClientRect().left - n.getBoundingClientRect().left - (n.clientWidth - a.offsetWidth) / 2;
  });
})();
