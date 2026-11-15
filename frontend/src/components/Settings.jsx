import { useState } from 'react'
import { KeyRound, UserRound, Database, RefreshCw, CheckCircle2, AlertTriangle } from 'lucide-react'
import { api, setToken, errorText } from '../lib/api'

function PasswordForm({ onChanged }) {
  const [f, setF] = useState({ current: '', next: '', confirm: '' })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const set = k => e => setF({ ...f, [k]: e.target.value })

  const submit = async e => {
    e.preventDefault(); setMsg(null)
    if (f.next.length < 8) return setMsg({ ok: false, text: 'New password must be at least 8 characters.' })
    if (f.next !== f.confirm) return setMsg({ ok: false, text: 'New password and confirmation do not match.' })
    setBusy(true)
    try {
      const { data } = await api.post('/api/auth/change-password', { current_password: f.current, new_password: f.next })
      setToken(data.access_token)
      onChanged(data.user)
      setF({ current: '', next: '', confirm: '' })
      setMsg({ ok: true, text: 'Password updated. Other sessions have been signed out.' })
    } catch (err) { setMsg({ ok: false, text: errorText(err) }) } finally { setBusy(false) }
  }

  return <form className="settings-card" onSubmit={submit}>
    <div className="settings-head"><KeyRound size={18} /><div><h3>Change password</h3><small>Minimum 8 characters. You stay signed in on this device.</small></div></div>
    {msg && <div className={msg.ok ? 'form-ok' : 'form-alert'}>{msg.ok ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />} {msg.text}</div>}
    <label>Current password<input type="password" autoComplete="current-password" value={f.current} onChange={set('current')} required /></label>
    <label>New password<input type="password" autoComplete="new-password" value={f.next} onChange={set('next')} required /></label>
    <label>Confirm new password<input type="password" autoComplete="new-password" value={f.confirm} onChange={set('confirm')} required /></label>
    <button className="primary-btn" disabled={busy}>{busy ? 'Saving…' : 'Update password'}</button>
  </form>
}

export default function Settings({ user, onUserChange, dataSource, onReload, reloading }) {
  return <div className="settings-grid">
    <section className="settings-card">
      <div className="settings-head"><UserRound size={18} /><div><h3>Account</h3><small>Signed-in profile</small></div></div>
      <dl className="kv"><dt>Username</dt><dd>{user.username}</dd><dt>Name</dt><dd>{user.display_name}</dd><dt>Email</dt><dd>{user.email}</dd></dl>
    </section>
    <PasswordForm onChanged={onUserChange} />
    <section className="settings-card wide">
      <div className="settings-head"><Database size={18} /><div><h3>Data source</h3><small>Configured with <code>DATA_SOURCE</code> · adapter file <code>backend/data_provider.py</code></small></div>
        <button className="refresh-btn" onClick={onReload} disabled={reloading}><RefreshCw size={15} className={reloading ? 'spin' : ''} /> Reload data</button></div>
      {dataSource && <>
        <p className="muted">Configured: <b>{dataSource.configured}</b> · Effective mode: <b>{dataSource.effective_mode}</b></p>
        <div className="table-wrap"><table className="data-table"><thead><tr><th>Indicator</th><th>Dataset</th><th>Mode</th><th>Records</th><th>Baseline</th></tr></thead><tbody>
          {dataSource.sources.map(s => <tr key={s.indicator}><td>{s.indicator}</td><td>{s.dataset}</td>
            <td><span className={`mode-pill ${s.source_mode === 'UNAVAILABLE' ? 'unavailable' : s.source_mode.startsWith('LIVE') || s.source_mode === 'ARCHIVE' ? 'live' : 'mock'}`}>{s.source_mode}</span>{s.fallback_reason && <small className="muted block">{s.fallback_reason}</small>}</td>
            <td>{s.records}</td><td>{s.baseline_period}</td></tr>)}
        </tbody></table></div></>}
    </section>
  </div>
}
