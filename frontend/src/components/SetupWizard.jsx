import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useApp } from '../context/AppContext';

const API = 'http://localhost:5050';

const INSTITUTIONS = {
  'Memorial Sloan Kettering Cancer Center': '001',
  'McGill University Health Centre':        '002',
};

const CODE_TO_NAME = Object.fromEntries(
  Object.entries(INSTITUTIONS).map(([name, code]) => [code, name])
);

export default function SetupWizard() {
  const { configure } = useApp();

  const [institution,      setInstitution]      = useState('');
  const [workspacePath,    setWorkspacePath]     = useState('');
  const [workspaceStatus,  setWorkspaceStatus]   = useState(null); // null | { exists, institutionCode }
  const [institutionLocked, setInstitutionLocked] = useState(false);
  const [loading,          setLoading]           = useState(false);
  const [error,            setError]             = useState('');
  const debounceRef = useRef(null);

  const checkWorkspace = useCallback(async (path) => {
    if (!path.trim()) { setWorkspaceStatus(null); setInstitutionLocked(false); return; }
    try {
      const res  = await fetch(`${API}/api/check-workspace?path=${encodeURIComponent(path)}`);
      const data = await res.json();
      setWorkspaceStatus(data);
      if (data.exists && data.institutionCode) {
        const name = CODE_TO_NAME[data.institutionCode] || data.institutionCode;
        setInstitution(name);
        setInstitutionLocked(true);
      } else {
        setInstitutionLocked(false);
      }
    } catch {
      setWorkspaceStatus(null);
      setInstitutionLocked(false);
    }
  }, []);

  // Pre-fill from last session and immediately run workspace detection
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('sarcomaai_last_config') || 'null');
      if (saved?.institution)   setInstitution(saved.institution);
      if (saved?.workspacePath) {
        setWorkspacePath(saved.workspacePath);
        checkWorkspace(saved.workspacePath);
      }
    } catch {}
  }, [checkWorkspace]);

  const valid = institution && workspacePath.trim();

  const handleSubmit = async () => {
    if (!valid) return;
    setLoading(true);
    setError('');
    try {
      await configure({
        institution: INSTITUTIONS[institution] || institution,
        workspacePath: workspacePath.trim(),
      });
    } catch (e) {
      setError(e.message || 'Setup failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'var(--bg-base)',
      padding: '2rem',
    }}>
      <div style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border)',
        borderRadius: 12,
        padding: '2.5rem',
        width: '100%',
        maxWidth: 520,
      }}>
        {/* Header */}
        <div style={{ marginBottom: '2rem', textAlign: 'center' }}>
          <div style={{ fontSize: 28, fontWeight: 700, color: 'var(--accent)', letterSpacing: '-0.5px' }}>
            SarcomaAI
          </div>
          <div style={{ color: 'var(--text-secondary)', marginTop: 6, fontSize: 14 }}>
            Select your workspace to get started
          </div>
        </div>

        {/* Institution */}
        <div style={{ marginBottom: '1.25rem' }}>
          <label style={labelStyle}>Institution</label>
          <select
            value={institution}
            onChange={e => { if (!institutionLocked) setInstitution(e.target.value); }}
            disabled={institutionLocked}
            style={{ ...selectStyle, opacity: institutionLocked ? 0.6 : 1, cursor: institutionLocked ? 'not-allowed' : 'pointer' }}
          >
            <option value="" disabled>-- Select Institution --</option>
            {Object.keys(INSTITUTIONS).map(n => <option key={n} value={n}>{n}</option>)}
          </select>
          {institutionLocked && (
            <div style={{ fontSize: 11, color: 'var(--accent)', marginTop: 4 }}>
              Loaded from existing workspace
            </div>
          )}
        </div>

        {/* Workspace path */}
        <div style={{ marginBottom: '1.25rem' }}>
          <label style={labelStyle}>SarcomaAI Workspace</label>
          <input
            type="text"
            value={workspacePath}
            onChange={e => {
              const val = e.target.value;
              setWorkspacePath(val);
              clearTimeout(debounceRef.current);
              debounceRef.current = setTimeout(() => checkWorkspace(val), 500);
            }}
            placeholder="/path/to/parent/folder"
            style={inputStyle}
          />
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>
            A <code style={{ fontFamily: 'monospace', color: 'var(--text-primary)' }}>sarcomaai_workspace/</code> folder will be created here
          </div>

          {/* Detection badge */}
          {workspaceStatus !== null && (
            <div style={{
              marginTop: 8,
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '4px 10px',
              borderRadius: 5,
              fontSize: 12,
              fontWeight: 600,
              background: workspaceStatus.exists
                ? 'rgba(91,142,244,0.12)'
                : 'rgba(34,197,94,0.12)',
              border: `1px solid ${workspaceStatus.exists ? 'rgba(91,142,244,0.3)' : 'rgba(34,197,94,0.3)'}`,
              color: workspaceStatus.exists ? 'var(--accent)' : 'var(--success)',
            }}>
              <span>{workspaceStatus.exists ? '◉' : '◎'}</span>
              {workspaceStatus.exists
                ? 'Existing workspace detected — will continue where you left off'
                : 'New workspace — folders will be created automatically'}
            </div>
          )}
        </div>

        {/* Workspace layout hint */}
        <div style={{
          marginBottom: '1.5rem',
          padding: '0.65rem 0.9rem',
          background: 'var(--bg-elevated)',
          borderRadius: 6,
          fontSize: 12,
          color: 'var(--text-secondary)',
          lineHeight: 1.9,
          fontFamily: 'monospace',
        }}>
          <div style={{ color: 'var(--text-primary)', fontWeight: 600, marginBottom: 4, fontFamily: 'inherit', fontSize: 11 }}>
            WORKSPACE LAYOUT
          </div>
          sarcomaai_workspace/<br />
          &nbsp;&nbsp;NEW_DICOMS/&nbsp;&nbsp;&nbsp;← drop new patient folders here<br />
          &nbsp;&nbsp;processed/&nbsp;&nbsp;&nbsp;&nbsp;← anonymized output (auto-managed)<br />
          &nbsp;&nbsp;sarcomaai.db&nbsp;&nbsp;← state &amp; history
        </div>

        {error && (
          <div style={{
            background: 'rgba(239,68,68,0.1)',
            border: '1px solid rgba(239,68,68,0.3)',
            borderRadius: 6,
            padding: '0.6rem 0.75rem',
            color: 'var(--danger)',
            fontSize: 13,
            marginBottom: '1rem',
          }}>
            {error}
          </div>
        )}

        <button
          onClick={handleSubmit}
          disabled={!valid || loading}
          style={{
            width: '100%',
            padding: '0.75rem',
            borderRadius: 8,
            border: 'none',
            background: valid && !loading ? 'var(--accent)' : 'var(--bg-elevated)',
            color: valid && !loading ? '#fff' : 'var(--text-secondary)',
            fontSize: 15,
            fontWeight: 600,
            cursor: valid && !loading ? 'pointer' : 'not-allowed',
            transition: 'background 0.2s',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 8,
          }}
        >
          {loading && (
            <span style={{
              width: 16, height: 16,
              border: '2px solid rgba(255,255,255,0.3)',
              borderTopColor: '#fff',
              borderRadius: '50%',
              display: 'inline-block',
              animation: 'spin 0.7s linear infinite',
            }} />
          )}
          {loading ? 'Connecting...' : 'Open Workspace'}
        </button>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        select option { background: var(--bg-elevated); }
      `}</style>
    </div>
  );
}

const labelStyle = {
  display: 'block',
  fontSize: 13,
  fontWeight: 500,
  color: 'var(--text-secondary)',
  marginBottom: 6,
  letterSpacing: '0.02em',
};

const inputStyle = {
  width: '100%',
  padding: '0.55rem 0.75rem',
  background: 'var(--bg-elevated)',
  border: '1px solid var(--border)',
  borderRadius: 6,
  color: 'var(--text-primary)',
  fontSize: 14,
  outline: 'none',
  boxSizing: 'border-box',
};

const selectStyle = {
  ...inputStyle,
};
