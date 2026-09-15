// Client-side blog search. Loads /search-index.json once, filters on submit,
// renders results in a Bootstrap-styled dropdown below the input.

(function () {
    var script = document.currentScript;
    if (!script) {
        var scripts = document.getElementsByTagName('script');
        for (var i = scripts.length - 1; i >= 0; i--) {
            if (scripts[i].src && scripts[i].src.indexOf('search.js') !== -1) {
                script = scripts[i];
                break;
            }
        }
    }
    var baseUrl = script ? new URL('.', script.src).href : '/';

    var INDEX_URL = baseUrl + 'search-index.json';
    var MAX_RESULTS = 20;
    var indexCache = null;

    function loadIndex() {
        if (indexCache) return Promise.resolve(indexCache);
        return fetch(INDEX_URL, { credentials: 'omit' }).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        }).then(function (data) {
            indexCache = data;
            return data;
        });
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    function score(post, ql) {
        var s = 0;
        if (post.title && post.title.toLowerCase().indexOf(ql) !== -1) s += 10;
        if (post.tags && post.tags.length) {
            for (var i = 0; i < post.tags.length; i++) {
                if (String(post.tags[i]).toLowerCase().indexOf(ql) !== -1) { s += 5; break; }
            }
        }
        if (post.summary && post.summary.toLowerCase().indexOf(ql) !== -1) s += 2;
        return s;
    }

    function renderResults(container, matches, q) {
        if (!matches.length) {
            container.innerHTML = '<div class="search-empty">没有匹配“' + escapeHtml(q) + '”的文章</div>';
            container.hidden = false;
            return;
        }
        var html = '';
        for (var i = 0; i < matches.length; i++) {
            var p = matches[i].p;
            var href = baseUrl + 'blog/' + p.slug + '.html';
            var tagsHtml = '';
            if (p.tags && p.tags.length) {
                for (var t = 0; t < p.tags.length; t++) {
                    tagsHtml += '<span class="badge bg-secondary">' + escapeHtml(p.tags[t]) + '</span> ';
                }
            }
            html += '<a class="search-item" href="' + href + '">'
                + '<div class="search-item-title">' + escapeHtml(p.title) + '</div>'
                + '<div class="search-item-meta">' + escapeHtml(p.date) + ' ' + tagsHtml + '</div>'
                + '</a>';
        }
        container.innerHTML = html;
        container.hidden = false;
    }

    function attach(form) {
        var container = form.parentElement;
        var input = form.querySelector('input[name="q"]');
        var results = container.querySelector('.search-results');
        if (!input || !results) return;

        var hideTimer = null;
        function hideSoon() {
            clearTimeout(hideTimer);
            hideTimer = setTimeout(function () { results.hidden = true; }, 180);
        }
        function cancelHide() {
            clearTimeout(hideTimer);
        }

        form.addEventListener('submit', function (e) {
            e.preventDefault();
            cancelHide();
            var q = input.value.trim();
            if (!q) { results.hidden = true; results.innerHTML = ''; return; }
            loadIndex().then(function (idx) {
                var ql = q.toLowerCase();
                var matches = [];
                for (var i = 0; i < idx.length; i++) {
                    var s = score(idx[i], ql);
                    if (s > 0) matches.push({ p: idx[i], s: s });
                }
                matches.sort(function (a, b) { return b.s - a.s; });
                matches = matches.slice(0, MAX_RESULTS);
                renderResults(results, matches, q);
            }).catch(function (err) {
                results.innerHTML = '<div class="search-empty">搜索失败：' + escapeHtml(err.message) + '</div>';
                results.hidden = false;
            });
        });

        input.addEventListener('input', function () {
            if (input.value.trim()) {
                form.dispatchEvent(new Event('submit'));
            } else {
                results.hidden = true;
                results.innerHTML = '';
            }
        });

        input.addEventListener('focus', function () {
            if (results.innerHTML && input.value.trim()) results.hidden = false;
        });
        input.addEventListener('blur', hideSoon);
        results.addEventListener('mousedown', cancelHide);
        results.addEventListener('mouseenter', cancelHide);
        results.addEventListener('mouseleave', hideSoon);
    }

    function injectStyles() {
        if (document.getElementById('search-js-styles')) return;
        var css = ''
            + '.search-container{position:relative}'
            + '.search-results{position:absolute;top:100%;right:0;left:auto;min-width:320px;max-width:480px;max-height:70vh;overflow-y:auto;background:#fff;border:1px solid #ddd;border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,.12);z-index:1080;margin-top:4px}'
            + '.search-results[hidden]{display:none}'
            + '.search-item{display:block;padding:.6rem .8rem;border-bottom:1px solid #eee;color:#333;text-decoration:none}'
            + '.search-item:last-child{border-bottom:none}'
            + '.search-item:hover{background:#f4f8ff;color:#0d6efd;text-decoration:none}'
            + '.search-item-title{font-weight:600;font-size:.95rem;margin-bottom:.2rem}'
            + '.search-item-meta{font-size:.8rem;color:#666}'
            + '.search-empty{padding:.8rem 1rem;color:#888;font-size:.9rem}';
        var style = document.createElement('style');
        style.id = 'search-js-styles';
        style.textContent = css;
        document.head.appendChild(style);
    }

    function init() {
        injectStyles();
        var forms = document.querySelectorAll('form[data-blog-search]');
        for (var i = 0; i < forms.length; i++) attach(forms[i]);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
