/* Message text is a display title; the original file name/download path stays intact. */
(function () {
  'use strict';
  const clean = value => String(value || '').replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f\u202a-\u202e\u2066-\u2069]/g, '');
  function title(item) {
    const lines = clean(item.caption).split(/\r?\n/).map(line => line.trim()).filter(Boolean);
    const line = lines.find(line => !/^(?:https?:\/\/|tg:\/\/|www\.)\S+$/i.test(line) && !/^@[\w_]+$/.test(line) && /[\p{L}\p{N}]/u.test(line));
    return (line || clean(item.file_name) || '未命名视频').replace(/^#{1,6}\s+/, '').slice(0, 600);
  }
  function details(item) {
    const caption = clean(item.caption), name = clean(item.file_name);
    return `${caption ? `<p class="media-file-name" title="${esc(name)}">文件 · ${esc(name)}</p>` : ''}<details class="media-description"><summary>${caption ? '展开 TG 说明与完整文件名' : '查看完整文件名'}</summary>${caption ? `<p class="media-source-caption">${esc(caption)}</p>` : ''}<p class="media-source-file">原文件：${esc(name)}</p></details>`;
  }
  window.mediaPresentation = { title, details };
})();
