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

// ── post photo gallery: slow auto-scroll + lightbox + swipe ──────────────────
(function(){
  var strip = document.getElementById('post-gallery');
  if (!strip) return;
  var photos = [];
  try { photos = JSON.parse(strip.getAttribute('data-photos')); } catch(e) {}
  var paused = false, raf = null;
  var SPEED = 0.4; // px per frame

  function tick(){
    if (!paused && !strip.classList.contains('lb-open')) {
      if (strip.scrollLeft + strip.clientWidth >= strip.scrollWidth - 4) {
        strip.scrollLeft = 0;
      } else {
        strip.scrollLeft += SPEED;
      }
    }
    raf = requestAnimationFrame(tick);
  }

  strip.addEventListener('mouseenter', function(){ paused = true; });
  strip.addEventListener('mouseleave', function(){ paused = false; });
  strip.addEventListener('touchstart', function(){ paused = true; });
  strip.addEventListener('touchend', function(){ setTimeout(function(){ paused = false; }, 4000); });

  var urls = photos.map(function(u){ return u.trim(); }).filter(Boolean);
  var idx = 0;
  var lb = document.getElementById('lightbox');
  var lbImg = document.getElementById('lightbox-img');
  var lbCap = document.getElementById('lightbox-caption');
  var lbCounter = document.getElementById('lb-counter');
  var prevBtn = document.getElementById('lb-prev');
  var nextBtn = document.getElementById('lb-next');

  function open(i){
    if (!lb || !urls.length) return;
    idx = (i + urls.length) % urls.length;
    lbImg.src = urls[idx];
    if (lbCap) lbCap.textContent = urls.length + ' photo' + (urls.length > 1 ? 's' : '') + ' in this post';
    if (lbCounter) lbCounter.textContent = (idx + 1) + ' / ' + urls.length;
    lb.classList.add('open');
    strip.classList.add('lb-open');
    paused = true;
  }
  function nav(dir){ open(idx + dir); }
  function close(){ if (lb) lb.classList.remove('open'); strip.classList.remove('lb-open'); paused = false; }

  Array.prototype.forEach.call(strip.querySelectorAll('img'), function(img, i){
    img.addEventListener('click', function(){ open(i); });
  });
  if (prevBtn) prevBtn.addEventListener('click', function(){ nav(-1); });
  if (nextBtn) nextBtn.addEventListener('click', function(){ nav(1); });
  var closeBtn = document.getElementById('lightbox-close');
  if (closeBtn) closeBtn.addEventListener('click', close);
  if (lb) lb.addEventListener('click', function(e){ if (e.target === lb) close(); });

  // swipe left / right on the lightbox image
  var sx = null, sy = null;
  if (lb) lb.addEventListener('touchstart', function(e){ sx = e.touches[0].clientX; sy = e.touches[0].clientY; }, {passive:true});
  if (lb) lb.addEventListener('touchend', function(e){
    if (sx === null) return;
    var dx = e.changedTouches[0].clientX - sx;
    var dy = e.changedTouches[0].clientY - sy;
    sx = null; sy = null;
    if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) nav(dx < 0 ? 1 : -1);
  }, {passive:true});

  document.addEventListener('keydown', function(e){
    if (e.key === 'Escape') close();
    if (e.key === 'ArrowLeft') nav(-1);
    if (e.key === 'ArrowRight') nav(1);
  });

  raf = requestAnimationFrame(tick);
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
