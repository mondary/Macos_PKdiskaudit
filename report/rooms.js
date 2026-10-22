/* Navigation par rooms du rapport PKDiskAudit.
   Une seule section visible à la fois, comme les « rooms » de l'app.
   Sans JS, toutes les sections restent empilées : rien ne disparaît. */
(function () {
  var nav = document.querySelector('.rooms');
  if (!nav) return;

  var tabs = Array.prototype.slice.call(document.querySelectorAll('.room-tab'));
  var rooms = Array.prototype.slice.call(document.querySelectorAll('.room'));
  if (!tabs.length || !rooms.length) return;

  var allBtn = document.querySelector('.rooms-all');
  var hint = document.querySelector('.rooms-hint');
  var navTop = 0;

  document.body.classList.add('rooms-ready');

  function roomFor(id) {
    for (var i = 0; i < rooms.length; i++) {
      if (rooms[i].id === id) return rooms[i];
    }
    return null;
  }

  function measure() {
    /* Position naturelle de la barre, insensible au sticky. */
    navTop = nav.offsetTop;
  }

  function setExpanded(on) {
    document.body.classList.toggle('rooms-open', on);
    if (allBtn) {
      allBtn.textContent = on ? 'Mode onglets' : 'Tout déplier';
      allBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
    }
    if (hint) hint.hidden = on;
  }

  function activate(id, opts) {
    opts = opts || {};
    var target = roomFor(id) || rooms[0];

    rooms.forEach(function (room) {
      room.classList.toggle('is-active', room === target);
    });
    tabs.forEach(function (tab) {
      var on = tab.getAttribute('data-room') === target.id;
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
      tab.tabIndex = on ? 0 : -1;
    });

    if (document.body.classList.contains('rooms-open')) setExpanded(false);

    if (!opts.silent && window.history && history.replaceState) {
      history.replaceState(null, '', '#' + target.id);
    }

    if (opts.scroll) {
      measure();
      window.scrollTo({
        top: Math.max(0, navTop),
        behavior: opts.instant ? 'auto' : 'smooth'
      });
    }
  }

  function indexOf(node) {
    return tabs.indexOf(node);
  }

  tabs.forEach(function (tab) {
    tab.addEventListener('click', function () {
      activate(tab.getAttribute('data-room'), { scroll: true });
    });
  });

  nav.addEventListener('keydown', function (event) {
    var from = indexOf(document.activeElement);
    if (from < 0) return;
    var to = null;
    if (event.key === 'ArrowRight') to = (from + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') to = (from - 1 + tabs.length) % tabs.length;
    else if (event.key === 'Home') to = 0;
    else if (event.key === 'End') to = tabs.length - 1;
    if (to === null) return;
    event.preventDefault();
    tabs[to].focus();
    activate(tabs[to].getAttribute('data-room'));
  });

  if (allBtn) {
    allBtn.addEventListener('click', function () {
      setExpanded(!document.body.classList.contains('rooms-open'));
    });
  }

  document.addEventListener('keydown', function (event) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)) return;
    var n = parseInt(event.key, 10);
    if (!n || n < 1 || n > tabs.length) return;
    event.preventDefault();
    activate(tabs[n - 1].getAttribute('data-room'), { scroll: true });
  });

  window.addEventListener('hashchange', function () {
    var id = (location.hash || '').replace('#', '');
    if (roomFor(id)) activate(id, { silent: true, scroll: true });
  });

  /* Point d'entrée pour l'app macOS : ouvre la room demandée, ou fait défiler
     vers une ancre qui ne serait pas une room. */
  window.scrollToSection = function (id) {
    if (roomFor(id)) {
      activate(id, { scroll: true });
      return;
    }
    var el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  window.addEventListener('resize', measure);
  measure();

  var initial = (location.hash || '').replace('#', '');
  var start = roomFor(initial) ? initial : rooms[0].id;
  activate(start, { silent: true });

  /* Un lien profond (#apps) fait sauter le navigateur vers l'ancre avant
     que l'on ait masqué les autres rooms : on replace la vue sur la barre. */
  if (roomFor(initial)) {
    var settle = function () { window.scrollTo(0, Math.max(0, navTop)); };
    requestAnimationFrame(settle);
    window.addEventListener('load', settle);
  }
})();
