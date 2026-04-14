/* ─────────────────────────────────────────
   DCT Risk Intelligence – Shared Utilities
───────────────────────────────────────── */

/** HTML-escape a value for safe DOM insertion */
function esc(val) {
  return String(val ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Map a risk score to a level class */
function scoreLevel(score) {
  if (score >= 13) return 'high';
  if (score >= 6)  return 'medium';
  return 'low';
}

/** Close any named modal */
function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('open');
}

/** Close modals when clicking the backdrop */
document.addEventListener('click', function (e) {
  if (e.target.classList.contains('modal-bg')) {
    e.target.classList.remove('open');
  }
});

/** Close modals on Escape */
document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-bg.open').forEach(el => el.classList.remove('open'));
  }
});

/**
 * Show a toast notification.
 * @param {string} msg
 * @param {'success'|'error'|'info'} type
 * @param {number} duration  ms before auto-dismiss
 */
function showToast(msg, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = msg;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity .3s';
    setTimeout(() => toast.remove(), 350);
  }, duration);
}
