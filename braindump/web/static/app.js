// braindump — client-side JS

// ─── Delete / Restore ───
async function deleteNote(id) {
    if (!confirm('Move this note to trash?')) return;
    var resp = await fetch('/api/notes/' + id, { method: 'DELETE' });
    if (resp.ok) {
        window.location.href = '/';
    } else {
        alert('Failed to delete note');
    }
}

async function restoreNote(id) {
    var resp = await fetch('/api/notes/' + id + '/restore', { method: 'POST' });
    if (resp.ok) {
        window.location.reload();
    } else {
        alert('Failed to restore note');
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
    // Escape key closes
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
// Convert bare URLs in text to clickable links, truncating display for long ones
function autoLinkURLs(html) {
    // Don't re-link URLs already inside href="" or <a> tags
    // Split by existing HTML tags and only process text nodes
    var parts = html.split(/(<[^>]+>)/);
    var inA = 0;
    for (var i = 0; i < parts.length; i++) {
        if (/^<a[\s>]/i.test(parts[i])) inA++;
        else if (/^<\/a>/i.test(parts[i])) inA--;
        else if (inA === 0 && !/^</.test(parts[i])) {
            parts[i] = parts[i].replace(
                /(https?:\/\/[^\s<>"')\]]+)/g,
                function (url) {
                    var display = url.length > 60 ? url.substring(0, 55) + '...' : url;
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
    // Auto-link any remaining bare URLs not already linked by markdown
    html = autoLinkURLs(html);
    return html;
}

document.addEventListener('DOMContentLoaded', function () {
    if (typeof marked === 'undefined') return;

    // Configure marked
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
});
