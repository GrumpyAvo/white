/* white — shared behaviours (replaces the inline <script>s on every page) */

// ── theme toggle ──────────────────────────────────────────────────────────────
(function(){
  var btn = document.getElementById('theme-toggle');
  if (btn) {
    btn.addEventListener('click', function(){
      var next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('theme', next);
      btn.textContent = next === 'dark' ? '☀ light' : '☾ dark';
    });
  }
})();

// ── secret font easter egg: type `nese` ───────────────────────────────────────
(function(){
  var FONT2_KEY = 'rf2active';
  var seq = '', target = 'nese';
  var active = sessionStorage.getItem(FONT2_KEY) === '1';

  function applyFont(on){
    document.documentElement.setAttribute('data-font2', on ? '1' : '0');
    sessionStorage.setItem(FONT2_KEY, on ? '1' : '0');
  }

  document.addEventListener('keydown', function(e){
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    seq += e.key.toLowerCase();
    if (seq.length > target.length) seq = seq.slice(-target.length);
    if (seq === target){
      seq = '';
      active = !active;
      applyFont(active);
    }
  });

  if (active) applyFont(true);
})();

// ── now playing ───────────────────────────────────────────────────────────────
(function(){
  var titleEl = document.getElementById('np-title');
  var artistEl = document.getElementById('np-artist');
  var statusEl = document.getElementById('np-status');
  var artEl = document.getElementById('np-art');
  if (!titleEl) return;

  function setArt(d){
    if (!artEl) return;
    artEl.innerHTML = (d && d.isPlaying && d.albumArt)
      ? '<img src="' + d.albumArt + '" style="width:100%;height:100%;object-fit:cover;display:block;border:0;" alt="album art" />'
      : '<span class="vinyl">◎</span>';
  }

  function render(d){
    if (d && d.isPlaying) {
      titleEl.textContent = d.title;
      if (artistEl) artistEl.textContent = d.artist;
      if (statusEl) statusEl.innerHTML = '<span style="color:var(--accent1)">▶</span> playing now';
    } else {
      titleEl.textContent = 'not playing';
      if (artistEl) artistEl.textContent = '—';
      if (statusEl) statusEl.innerHTML = '◈ offline';
    }
    setArt(d);
  }

  function refresh(){
    fetch('/api/now-playing')
      .then(function(r){ return r.json(); })
      .then(function(d){ render(d); })
      .catch(function(){ /* keep last state */ });
  }

  render({
    isPlaying: (titleEl.textContent && titleEl.textContent !== 'not playing'),
    albumArt: artEl ? (artEl.getAttribute('data-art') || '') : ''
  });
  refresh();
  setInterval(refresh, 10000);
})();
