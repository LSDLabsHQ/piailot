(function() {
  var THEMES = {
    terminal: {},
    light: {
      '--bg': '#f5f5f5', '--surface': '#ffffff', '--border': '#e0e0e0',
      '--green': '#16a34a', '--green-dim': '#15803d', '--green-glow': 'rgba(22,163,74,0.08)',
      '--amber': '#d97706', '--red': '#ff4444', '--cyan': '#0284c7',
      '--text': '#1f2937', '--text-dim': '#6b7280',
      '--accent': '#16a34a', '--accent-dim': 'rgba(22,163,74,0.08)',
      '--muted': '#6b7280', '--yellow': '#d97706', '--input-bg': '#f0f0f0',
      '--font': "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif"
    },
    soft: {
      '--bg': '#fdf6f0', '--surface': '#ffffff', '--border': '#f0e4d8',
      '--green': '#8b5cf6', '--green-dim': '#7c3aed', '--green-glow': 'rgba(139,92,246,0.08)',
      '--amber': '#f59e0b', '--red': '#f43f5e', '--cyan': '#06b6d4',
      '--text': '#44403c', '--text-dim': '#a8a29e',
      '--accent': '#8b5cf6', '--accent-dim': 'rgba(139,92,246,0.08)',
      '--muted': '#a8a29e', '--yellow': '#f59e0b', '--input-bg': '#faf5ef',
      '--font': "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif"
    }
  };

  var ALL_KEYS = {};
  Object.keys(THEMES).forEach(function(t) {
    Object.keys(THEMES[t]).forEach(function(k) { ALL_KEYS[k] = true; });
  });
  ALL_KEYS = Object.keys(ALL_KEYS);

  var current = localStorage.getItem('piailot_theme') || 'terminal';
  if (!THEMES[current]) current = 'terminal';

  function apply(name) {
    if (!THEMES[name]) return;
    current = name;
    var root = document.documentElement;
    ALL_KEYS.forEach(function(k) { root.style.removeProperty(k); });
    var vars = THEMES[name];
    Object.keys(vars).forEach(function(k) {
      root.style.setProperty(k, vars[k]);
    });
    localStorage.setItem('piailot_theme', name);
    document.querySelectorAll('.theme-picker').forEach(function(p) { p.value = name; });
  }

  // Apply before paint
  apply(current);

  // Inject picker styles
  var s = document.createElement('style');
  s.textContent = '.theme-picker{background:var(--bg);color:var(--amber,var(--yellow,#d97706));border:1px solid var(--border);padding:4px 8px;border-radius:4px;font-family:inherit;font-size:0.72em;cursor:pointer;}.theme-picker:focus{outline:1px solid var(--amber,var(--yellow,#d97706));}';
  document.head.appendChild(s);

  window.piailotThemes = {
    apply: apply,
    current: function() { return current; },
    names: Object.keys(THEMES),
    picker: function(parent) {
      var sel = document.createElement('select');
      sel.className = 'theme-picker';
      Object.keys(THEMES).forEach(function(name) {
        var opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        sel.appendChild(opt);
      });
      sel.value = current;
      sel.addEventListener('change', function() { apply(sel.value); });
      parent.appendChild(sel);
      return sel;
    }
  };
})();
