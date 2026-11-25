// Main JS
function syncThemeIcon() {
  const theme = document.documentElement.getAttribute('data-theme') || 'light';
  const icon = document.getElementById('themeToggleIcon');
  if (icon) {
    icon.textContent = (theme === 'dark') ? '☀️' : '🌙';
  }
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'light';
  const next = (current === 'dark') ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  try {
    localStorage.setItem('rupeeroute_theme', next);
  } catch (e) {}
  syncThemeIcon();
}

document.addEventListener('DOMContentLoaded', function () {
  syncThemeIcon();
  // Auto dismiss flash messages after 4 seconds
  setTimeout(function () {
    document.querySelectorAll('.flash-item').forEach(function (el) {
      el.style.opacity = '0';
      setTimeout(function () { el.remove(); }, 300);
    });
  }, 4000);
});

// Toggle User Dropdown Menu
function toggleUserDropdown(event) {
  if (event) {
    event.stopPropagation();
    event.preventDefault();
  }
  const notifDropdown = document.getElementById('notificationDropdownMenu');
  if (notifDropdown) notifDropdown.style.display = 'none';
  const dropdown = document.getElementById('userDropdownMenu');
  if (dropdown) {
    const isVisible = dropdown.style.display === 'block';
    dropdown.style.display = isVisible ? 'none' : 'block';
  }
}

// Toggle Notification Dropdown Menu
function toggleNotificationDropdown(event) {
  if (event) {
    event.stopPropagation();
    event.preventDefault();
  }
  const userDropdown = document.getElementById('userDropdownMenu');
  if (userDropdown) userDropdown.style.display = 'none';
  const dropdown = document.getElementById('notificationDropdownMenu');
  if (dropdown) {
    const isVisible = dropdown.style.display === 'block';
    dropdown.style.display = isVisible ? 'none' : 'block';
  }
}

// Close dropdowns when clicking outside
document.addEventListener('click', function (event) {
  const userDropdown = document.getElementById('userDropdownMenu');
  const userTrigger = document.getElementById('threeLineBtn');
  if (userDropdown && userDropdown.style.display === 'block') {
    if (!(userTrigger && (userTrigger.contains(event.target) || userTrigger === event.target)) && !userDropdown.contains(event.target)) {
      userDropdown.style.display = 'none';
    }
  }

  const notifDropdown = document.getElementById('notificationDropdownMenu');
  const notifTrigger = document.getElementById('notifBellBtn');
  if (notifDropdown && notifDropdown.style.display === 'block') {
    if (!(notifTrigger && (notifTrigger.contains(event.target) || notifTrigger === event.target)) && !notifDropdown.contains(event.target)) {
      notifDropdown.style.display = 'none';
    }
  }
});

// =============================================================================
// REUSABLE CLIENT-SIDE TABLE PAGINATOR (10 Entries Per Page)
// =============================================================================
const RupeePaginator = {
  configs: {},

  register: function (opts) {
    this.configs[opts.key] = {
      key: opts.key,
      tbodyId: opts.tbodyId,
      rowSelector: opts.rowSelector,
      controlsId: opts.controlsId,
      pageSize: opts.pageSize || 10,
      currentPage: 1,
    };
  },

  apply: function (key, targetPage) {
    const cfg = this.configs[key];
    if (!cfg) return;

    const tbody = document.getElementById(cfg.tbodyId);
    const controls = document.getElementById(cfg.controlsId);
    if (!tbody) return;

    const allRows = Array.from(tbody.querySelectorAll(cfg.rowSelector));
    const matchingRows = [];
    allRows.forEach(function (row) {
      if (row.dataset.filterHidden === '1') {
        row.style.display = 'none';
      } else {
        matchingRows.push(row);
      }
    });

    const total = matchingRows.length;
    if (total === 0) {
      if (controls) controls.style.display = 'none';
      return;
    }

    const totalPages = Math.max(1, Math.ceil(total / cfg.pageSize));
    const page = Math.max(1, Math.min(targetPage || cfg.currentPage || 1, totalPages));
    cfg.currentPage = page;

    const startIdx = (page - 1) * cfg.pageSize;
    const endIdx = Math.min(startIdx + cfg.pageSize, total);

    matchingRows.forEach(function (row, idx) {
      row.style.display = (idx >= startIdx && idx < endIdx) ? '' : 'none';
    });

    if (!controls) return;
    controls.style.display = 'flex';
    controls.innerHTML = '';

    // Left Summary: "Showing 10 of 25 (Entries 1–10 • Page 1 of 3)"
    const info = document.createElement('div');
    info.className = 'pagination-info';
    info.innerHTML = `Showing <strong>${endIdx} of ${total}</strong> (Entries ${startIdx + 1}&ndash;${endIdx} &bull; Page ${page} of ${totalPages})`;
    controls.appendChild(info);

    // Right Page Buttons
    const btnGroup = document.createElement('div');
    btnGroup.className = 'pagination-controls';

    const prevBtn = document.createElement('button');
    prevBtn.type = 'button';
    prevBtn.className = 'pagination-btn';
    prevBtn.textContent = '← Prev';
    prevBtn.disabled = (page <= 1);
    prevBtn.onclick = () => RupeePaginator.apply(key, page - 1);
    btnGroup.appendChild(prevBtn);

    const pagesToShow = [];
    for (let p = 1; p <= totalPages; p++) {
      if (p === 1 || p === totalPages || Math.abs(p - page) <= 1) {
        pagesToShow.push(p);
      } else if (pagesToShow[pagesToShow.length - 1] !== '...') {
        pagesToShow.push('...');
      }
    }

    pagesToShow.forEach(function (item) {
      if (item === '...') {
        const span = document.createElement('span');
        span.style.padding = '0 0.25rem';
        span.style.color = '#94a3b8';
        span.style.fontWeight = '700';
        span.textContent = '...';
        btnGroup.appendChild(span);
      } else {
        const pBtn = document.createElement('button');
        pBtn.type = 'button';
        pBtn.className = 'pagination-btn' + (item === page ? ' pagination-btn--active' : '');
        pBtn.textContent = String(item);
        pBtn.onclick = () => RupeePaginator.apply(key, item);
        btnGroup.appendChild(pBtn);
      }
    });

    const nextBtn = document.createElement('button');
    nextBtn.type = 'button';
    nextBtn.className = 'pagination-btn';
    nextBtn.textContent = 'Next →';
    nextBtn.disabled = (page >= totalPages);
    nextBtn.onclick = () => RupeePaginator.apply(key, page + 1);
    btnGroup.appendChild(nextBtn);

    controls.appendChild(btnGroup);
  },

  revealRowById: function (key, rowId) {
    const cfg = this.configs[key];
    if (!cfg || !rowId) return false;
    const tbody = document.getElementById(cfg.tbodyId);
    if (!tbody) return false;
    const matchingRows = Array.from(tbody.querySelectorAll(cfg.rowSelector)).filter(r => r.dataset.filterHidden !== '1');
    const idx = matchingRows.findIndex(r => r.id === rowId);
    if (idx === -1) return false;
    const targetPage = Math.floor(idx / cfg.pageSize) + 1;
    this.apply(key, targetPage);
    const targetEl = document.getElementById(rowId);
    if (targetEl) {
      targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
      targetEl.classList.add('row-highlight-flash');
      setTimeout(() => targetEl.classList.remove('row-highlight-flash'), 3000);
    }
    return true;
  }
};

// =============================================================================
// INTERACTIVE SVG PIE CHART RENDERER FOR ANALYTICS DASHBOARD
// =============================================================================
function renderAnalyticsPieChart(chartWrapId, legendId, dataset, emptyHintText) {
  const wrap = document.getElementById(chartWrapId);
  const legend = document.getElementById(legendId);
  const tooltip = document.getElementById('analyticsFloatingTooltip');
  if (!wrap || !legend) return;

  wrap.innerHTML = '';
  legend.innerHTML = '';

  const slices = (dataset && dataset.slices) ? dataset.slices : [];
  if (slices.length === 0) {
    wrap.innerHTML = `
      <svg viewBox="0 0 220 220" class="analytics-pie-svg">
        <circle cx="110" cy="110" r="88" fill="#f1f5f9" stroke="#e2e8f0" stroke-width="2" stroke-dasharray="6 4"></circle>
        <text x="110" y="114" text-anchor="middle" fill="#94a3b8" font-size="13" font-weight="700">No Data</text>
      </svg>
    `;
    legend.innerHTML = `<div style="color: var(--text-muted); font-size: 0.85rem; line-height: 1.5;">${emptyHintText || 'No entries recorded for this period.'}</div>`;
    return;
  }

  const svgNS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('viewBox', '0 0 220 220');
  svg.setAttribute('class', 'analytics-pie-svg');

  const cx = 110;
  const cy = 110;
  const r = 92;

  function showTip(evt, slice) {
    if (!tooltip) return;
    tooltip.innerHTML = `
      <div>${escapeHtml(slice.name)} (${slice.percentage}%)</div>
      <span class="analytics-tooltip__amount">${escapeHtml(slice.amount_formatted)}</span>
    `;
    tooltip.style.display = 'block';
    const x = Math.min(window.innerWidth - 190, Math.max(10, evt.clientX + 14));
    const y = Math.max(10, evt.clientY - 56);
    tooltip.style.left = x + 'px';
    tooltip.style.top = y + 'px';
  }

  function hideTip() {
    if (tooltip) tooltip.style.display = 'none';
  }

  function highlightPair(idx, active) {
    const shape = svg.querySelector(`[data-slice-idx="${idx}"]`);
    const leg = legend.querySelector(`[data-legend-idx="${idx}"]`);
    if (shape) shape.classList.toggle('is-hovered', active);
    if (leg) leg.classList.toggle('is-hovered', active);
  }

  let currentAngle = -Math.PI / 2;
  const totalVal = slices.reduce((acc, s) => acc + (s.amount || 0), 0);

  slices.forEach(function (slice, idx) {
    const fraction = totalVal > 0 ? (slice.amount / totalVal) : 0;
    let shape;

    if (slices.length === 1 || fraction >= 0.999) {
      shape = document.createElementNS(svgNS, 'circle');
      shape.setAttribute('cx', cx);
      shape.setAttribute('cy', cy);
      shape.setAttribute('r', r);
      shape.setAttribute('fill', slice.color);
      shape.setAttribute('stroke', '#ffffff');
      shape.setAttribute('stroke-width', '2');
    } else {
      const sliceAngle = fraction * 2 * Math.PI;
      const startAngle = currentAngle;
      const endAngle = currentAngle + sliceAngle;
      currentAngle = endAngle;

      const x1 = cx + r * Math.cos(startAngle);
      const y1 = cy + r * Math.sin(startAngle);
      const x2 = cx + r * Math.cos(endAngle);
      const y2 = cy + r * Math.sin(endAngle);
      const largeArc = sliceAngle > Math.PI ? 1 : 0;

      const d = `M ${cx} ${cy} L ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${largeArc} 1 ${x2.toFixed(2)} ${y2.toFixed(2)} Z`;
      shape = document.createElementNS(svgNS, 'path');
      shape.setAttribute('d', d);
      shape.setAttribute('fill', slice.color);
      shape.setAttribute('stroke', '#ffffff');
      shape.setAttribute('stroke-width', '2');
    }

    shape.setAttribute('class', 'analytics-pie-slice');
    shape.setAttribute('data-slice-idx', idx);
    shape.addEventListener('mouseenter', function (evt) {
      highlightPair(idx, true);
      showTip(evt, slice);
    });
    shape.addEventListener('mousemove', function (evt) {
      showTip(evt, slice);
    });
    shape.addEventListener('mouseleave', function () {
      highlightPair(idx, false);
      hideTip();
    });
    svg.appendChild(shape);
  });

  // Render % Labels on slices >= 7% (so labels never overlap)
  let labelAngle = -Math.PI / 2;
  slices.forEach(function (slice) {
    const fraction = totalVal > 0 ? (slice.amount / totalVal) : 0;
    const sliceAngle = fraction * 2 * Math.PI;
    const midAngle = labelAngle + (sliceAngle / 2);
    labelAngle += sliceAngle;

    if (slice.percentage >= 7) {
      const lr = slices.length === 1 ? 0 : (r * 0.62);
      const lx = cx + lr * Math.cos(midAngle);
      const ly = cy + lr * Math.sin(midAngle) + 4;
      const txt = document.createElementNS(svgNS, 'text');
      txt.setAttribute('x', lx.toFixed(1));
      txt.setAttribute('y', ly.toFixed(1));
      txt.setAttribute('text-anchor', 'middle');
      txt.setAttribute('fill', '#ffffff');
      txt.setAttribute('font-size', '11');
      txt.setAttribute('font-weight', '800');
      txt.setAttribute('pointer-events', 'none');
      txt.textContent = slice.percentage + '%';
      svg.appendChild(txt);
    }
  });

  wrap.appendChild(svg);

  // Legend: Only Category Name and Percentage until hover!
  slices.forEach(function (slice, idx) {
    const item = document.createElement('div');
    item.className = 'analytics-legend-item';
    item.setAttribute('data-legend-idx', idx);
    item.innerHTML = `
      <div class="analytics-legend-left">
        <span class="analytics-legend-dot" style="background: ${slice.color};"></span>
        <span class="analytics-legend-name" title="${escapeHtml(slice.name)}">${escapeHtml(slice.name)}</span>
      </div>
      <span class="analytics-legend-pct">${slice.percentage}%</span>
    `;
    item.addEventListener('mouseenter', function (evt) {
      highlightPair(idx, true);
      showTip(evt, slice);
    });
    item.addEventListener('mousemove', function (evt) {
      showTip(evt, slice);
    });
    item.addEventListener('mouseleave', function () {
      highlightPair(idx, false);
      hideTip();
    });
    legend.appendChild(item);
  });
}

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
