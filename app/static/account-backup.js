(function () {
  'use strict';
  const fields = importing => `<label>当前服务器的管理员密码<input name="admin" type="password" autocomplete="current-password" required maxlength="200"></label>
    <label>备份文件密码（至少 12 位）<input name="backup" type="password" autocomplete="${importing ? 'off' : 'new-password'}" required minlength="12" maxlength="200"></label>
    ${importing ? '' : '<label>再次输入备份密码<input name="confirm" type="password" autocomplete="new-password" required minlength="12" maxlength="200"></label>'}`;
  async function post(path, body) {
    const response = await fetch('/api/accounts/backup/' + path, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === 'string' ? data.detail : '操作未完成，请检查文件和密码后重试');
    }
    return response;
  }
  window.openAccountBackup = function (id) {
    const rows = id ? accountRows.filter(row => row.id === id) : accountRows;
    modal(`<h3>导出账号备份</h3><p class="muted backup-intro">备份包含 Telegram 登录授权和 API 配置，以独立密码加密。文件不包含视频、聊天记录或后台密码。</p>
      <form id="accountBackupForm"><fieldset class="backup-accounts"><legend>选择账号</legend>${rows.map(row => `<label><input type="checkbox" name="account" value="${row.id}" checked> ${esc(row.label)}</label>`).join('')}</fieldset>
      ${fields(false)}<p class="backup-note">请保存好文件和备份密码。迁移后停止旧实例使用该账号，避免同一授权在两台服务器同时连接。已结束的 Telegram 会话不能通过旧备份重新激活。</p>
      <button type="submit">加密并下载到本机</button><div class="error" role="status"></div></form>`);
    const form = document.querySelector('#accountBackupForm');
    form.onsubmit = async event => {
      event.preventDefault();
      const error = form.querySelector('.error'), button = form.querySelector('button');
      const selected = [...form.querySelectorAll('[name=account]:checked')].map(x => Number(x.value));
      if (!selected.length) { error.textContent = '请至少选择一个账号'; return; }
      if (form.elements.backup.value !== form.elements.confirm.value) { error.textContent = '两次输入的备份密码不一致'; return; }
      button.disabled = true; error.textContent = '正在加密备份…';
      try {
        const response = await post('export', { admin_password: form.elements.admin.value,
          backup_password: form.elements.backup.value, account_ids: selected });
        const blob = await response.blob(), url = URL.createObjectURL(blob), link = document.createElement('a');
        link.href = url; link.download = `nebula-accounts-${new Date().toISOString().slice(0, 10)}.nebula`;
        document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 60000);
        form.reset();
        if (button.isConnected) closeModal();
        toast('加密备份已交给浏览器下载，请妥善保存');
      } catch (ex) { if (button.isConnected) { error.textContent = ex.message; button.disabled = false; } }
    };
  };
  window.openAccountRestore = function () {
    modal(`<h3>从备份导入账号</h3><p class="muted backup-intro">输入本服务器的管理员密码，以及导出时设置的备份密码。导入只新增账号，重复登录授权会跳过；不会修改现有账号和密码。</p>
      <form id="accountRestoreForm"><label>加密备份文件<input name="file" type="file" accept=".nebula,application/octet-stream" required></label>
      ${fields(true)}<p class="backup-note">迁移前请停止旧服务器使用该账号。导入后手动切换账号以连接 Telegram；视频和任务需另外迁移数据目录。</p>
      <button type="submit">解密并恢复账号</button><div class="error" role="status"></div></form>`);
    const form = document.querySelector('#accountRestoreForm');
    form.onsubmit = async event => {
      event.preventDefault();
      const error = form.querySelector('.error'), button = form.querySelector('button');
      const file = form.elements.file.files[0];
      if (!file || file.size > 2 * 1024 * 1024) { error.textContent = '请选择不超过 2 MB 的 .nebula 备份'; return; }
      button.disabled = true; error.textContent = '正在校验并恢复…';
      try {
        const response = await post('import', { admin_password: form.elements.admin.value,
          backup_password: form.elements.backup.value, backup: await file.text() });
        const data = await response.json(); form.reset();
        if (button.isConnected) closeModal();
        toast(`已恢复 ${data.imported} 个账号${data.skipped ? `，跳过 ${data.skipped} 个重复授权` : ''}`);
        await go('accounts');
      } catch (ex) { if (button.isConnected) { error.textContent = ex.message; button.disabled = false; } }
    };
  };
})();
