// braindump — client-side interactions
// Beautiful, smooth, purposeful.

// ─── Toast Notifications ───
function showToast(message, type) {
    var container = document.getElementById('toastContainer');
    if (!container) return;
    var toast = document.createElement('div');
    toast.className = 'toast' + (type ? ' toast-' + type : '');
    toast.textContent = message;
    container.appendChild(toast);
    requestAnimationFrame(function () {
        toast.classList.add('visible');
    });
    setTimeout(function () {
        toast.classList.remove('visible');
        setTimeout(function () { toast.remove(); }, 350);
    }, 3000);
}

// ─── Delete / Restore ───
async function deleteNote(id) {
    if (!confirm('Move this note to trash?')) return;
    var resp = await fetch('/api/notes/' + id, { method: 'DELETE' });
    if (resp.ok) {
        showToast('Note moved to trash', 'success');
        setTimeout(function () { window.location.href = '/'; }, 800);
    } else {
        showToast('Failed to delete note', 'danger');
    }
}

async function restoreNote(id) {
    var resp = await fetch('/api/notes/' + id + '/restore', { method: 'POST' });
    if (resp.ok) {
        showToast('Note restored', 'success');
        setTimeout(function () { window.location.reload(); }, 800);
    } else {
        showToast('Failed to restore note', 'danger');
    }
}

// ─── Image Lightbox ───
function openLightbox(src) {
    var overlay = document.createElement('div');
    overlay.className = 'lightbox-overlay';
    overlay.innerHTML = '<span class="lightbox-close">&times;</span><img src="' + src + '" alt="">';
    overlay.addEventListener('click', function () {
        overlay.classList.remove('active');
        setTimeout(function () { overlay.remove(); }, 300);
    });
    var onKey = function (e) {
        if (e.key === 'Escape') {
            overlay.classList.remove('active');
            setTimeout(function () { overlay.remove(); }, 300);
            document.removeEventListener('keydown', onKey);
        }
    };
    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
    requestAnimationFrame(function () { overlay.classList.add('active'); });
}

// ─── URL auto-linking ───
function autoLinkURLs(html) {
    var parts = html.split(/(<[^>]+>)/);
    var inA = 0;
    for (var i = 0; i < parts.length; i++) {
        if (/^<a[\s>]/i.test(parts[i])) inA++;
        else if (/^<\/a>/i.test(parts[i])) inA--;
        else if (inA === 0 && !/^</.test(parts[i])) {
            parts[i] = parts[i].replace(
                /(https?:\/\/[^\s<>"')\]]+)/g,
                function (url) {
                    var display = url.length > 60 ? url.substring(0, 55) + '\u2026' : url;
                    return '<a href="' + url + '" class="auto-link" target="_blank" rel="noopener">' + display + '</a>';
                }
            );
        }
    }
    return parts.join('');
}

// ─── Markdown Rendering ───
function decodeHTMLEntities(str) {
    var textarea = document.createElement('textarea');
    textarea.innerHTML = str;
    return textarea.value;
}

function renderMarkdown(raw) {
    if (typeof marked === 'undefined') return null;
    var decoded = decodeHTMLEntities(raw);
    var html = marked.parse(decoded);
    html = autoLinkURLs(html);
    return html;
}

// ─── Relative Date Labels ───
function getRelativeDateLabel(dateStr) {
    var today = new Date();
    today.setHours(0, 0, 0, 0);
    var parts = dateStr.split('-');
    var target = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
    target.setHours(0, 0, 0, 0);
    var diff = Math.round((today - target) / 86400000);
    if (diff === 0) return 'Today';
    if (diff === 1) return 'Yesterday';
    if (diff < 7) return diff + ' days ago';
    if (diff < 30) {
        var weeks = Math.floor(diff / 7);
        return weeks === 1 ? '1 week ago' : weeks + ' weeks ago';
    }
    if (diff < 365) {
        var months = Math.floor(diff / 30);
        return months === 1 ? '1 month ago' : months + ' months ago';
    }
    var years = Math.floor(diff / 365);
    return years === 1 ? '1 year ago' : years + ' years ago';
}

// ─── Header scroll shadow ───
function initHeaderScroll() {
    var header = document.querySelector('.site-header');
    if (!header) return;
    var scrolled = false;
    window.addEventListener('scroll', function () {
        var isScrolled = window.scrollY > 10;
        if (isScrolled !== scrolled) {
            scrolled = isScrolled;
            if (scrolled) {
                header.classList.add('scrolled');
            } else {
                header.classList.remove('scrolled');
            }
        }
    }, { passive: true });
}

// ─── Main Init ───
document.addEventListener('DOMContentLoaded', function () {

    // Header scroll shadow
    initHeaderScroll();

    // Configure marked.js
    if (typeof marked !== 'undefined') {
        marked.setOptions({
            breaks: true,
            gfm: true,
        });

        // Render detail page content
        document.querySelectorAll('.note-detail-content.markdown-body[data-markdown]').forEach(function (el) {
            var html = renderMarkdown(el.getAttribute('data-markdown'));
            if (html) el.innerHTML = html;
        });

        // Render card previews
        document.querySelectorAll('.note-text.markdown-card[data-markdown]').forEach(function (el) {
            var html = renderMarkdown(el.getAttribute('data-markdown'));
            if (html) el.innerHTML = html;
        });
    }

    // Relative date labels
    document.querySelectorAll('.date-relative[data-date]').forEach(function (el) {
        var dateStr = el.getAttribute('data-date');
        if (dateStr) {
            el.textContent = getRelativeDateLabel(dateStr);
        }
    });

    // Clickable tags in timeline cards
    document.querySelectorAll('.note-card .tag[data-tag]').forEach(function (el) {
        el.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            window.location.href = '/?tag=' + encodeURIComponent(el.getAttribute('data-tag'));
        });
    });

    // Stop click propagation on videos/audios inside card links
    document.querySelectorAll('.note-card-link video, .note-card-link audio').forEach(function (el) {
        el.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); });
    });

    // Keyboard shortcut: / to focus search
    document.addEventListener('keydown', function (e) {
        if (e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey) {
            var active = document.activeElement;
            if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.tagName === 'SELECT')) return;
            var searchInput = document.querySelector('.search-input');
            if (searchInput) {
                e.preventDefault();
                searchInput.focus();
            }
        }
    });
});
