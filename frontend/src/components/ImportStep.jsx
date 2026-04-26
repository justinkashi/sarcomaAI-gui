import React, { useState, useRef, useCallback } from 'react';
import { useApp } from '../context/AppContext';

const API = 'http://localhost:5050';

export default function ImportStep() {
  const { skipImport, finishImport } = useApp();

  const [sourcePath,   setSourcePath]   = useState('');
  const [scanStatus,   setScanStatus]   = useState('idle'); // idle | scanning | ready | not-found
  const [folders,      setFolders]      = useState([]);
  const [importStatus, setImportStatus] = useState('idle'); // idle | running | done | error
  const [log,          setLog]          = useState([]);     // { folder, status }
  const [picking,      setPicking]      = useState(false);  // native picker in progress

  const debounceRef = useRef(null);

  const scanSource = useCallback(async (path) => {
    if (!path.trim()) { setScanStatus('idle'); setFolders([]); return; }
    setScanStatus('scanning');
    try {
      const res  = await fetch(`${API}/api/scan-source?path=${encodeURIComponent(path)}`);
      if (!res.ok) { setScanStatus('not-found'); setFolders([]); return; }
      const data = await res.json();
      setFolders(data.folders);
      setScanStatus('ready');
    } catch {
      setScanStatus('not-found');
      setFolders([]);
    }
  }, []);

  const handlePathChange = (e) => {
    const val = e.target.value;
    setSourcePath(val);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => scanSource(val), 500);
  };

  // Opens a native macOS folder picker via the Flask backend (osascript).
  // The browser never touches the path — Python resolves it and returns JSON.
  const pickFolder = async () => {
    setPicking(true);
    try {
      const res  = await fetch(`${API}/api/pick-folder`);
      const data = await res.json();
      if (data.path) {
        setSourcePath(data.path);
        scanSource(data.path);
      }
    } catch {
      // silently ignore — user can still type the path manually
    } finally {
      setPicking(false);
    }
  };

  const startImport = () => {
    if (!sourcePath.trim() || folders.length === 0) return;
    setImportStatus('running');
    setLog([]);

    const es = new EventSource(
      `${API}/api/import-stream?source=${encodeURIComponent(sourcePath)}`
    );

    es.onmessage = (e) => {
      const data = JSON.parse(e.data);
      if (data.done) {
        es.close();
        setImportStatus('done');
        finishImport();
      } else {
        setLog(prev => [...prev, data]);
      }
    };

    es.onerror = () => {
      es.close();
      setImportStatus('error');
    };
  };

  const isRunning = importStatus === 'running';
  const isDone    = importStatus === 'done';

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
        maxWidth: 560,
      }}>
        {/* Header */}
        <div style={{ marginBottom: '2rem' }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 6 }}>
            Import New Patients
          </div>
          <div style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
            Point to your source DICOM folder. Only patient folders not already in your workspace
            will be copied into the inbox — existing patients are automatically skipped.
          </div>
        </div>

        {/* Source path */}
        <div style={{ marginBottom: '1.25rem' }}>
          <label style={labelStyle}>Source DICOM Folder</label>

          {/* Browse button + text input row */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
            <input
              type="text"
              value={sourcePath}
              onChange={handlePathChange}
              disabled={isRunning || picking}
              placeholder="/path/to/source/DICOM"
              style={{
                ...inputStyle,
                flex: 1,
                opacity: (isRunning || picking) ? 0.6 : 1,
              }}
            />
            <button
              onClick={pickFolder}
              disabled={isRunning || picking}
              style={{
                padding: '0 1rem',
                borderRadius: 6,
                border: '1px solid var(--border)',
                background: 'var(--bg-elevated)',
                color: 'var(--text-primary)',
                fontSize: 13,
                fontWeight: 500,
                cursor: (isRunning || picking) ? 'not-allowed' : 'pointer',
                whiteSpace: 'nowrap',
                opacity: (isRunning || picking) ? 0.6 : 1,
              }}
            >
              {picking ? 'Choosing…' : 'Browse…'}
            </button>
          </div>

          {/* Scan status */}
          {scanStatus === 'scanning' && (
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 6 }}>
              Scanning...
            </div>
          )}
          {scanStatus === 'not-found' && (
            <div style={{ fontSize: 12, color: 'var(--danger)', marginTop: 6 }}>
              Path not found or not accessible
            </div>
          )}
          {scanStatus === 'ready' && folders.length === 0 && (
            <div style={{ fontSize: 12, color: 'var(--warning)', marginTop: 6 }}>
              No patient folders found at this path
            </div>
          )}
        </div>

        {/* Patient folder chips */}
        {scanStatus === 'ready' && folders.length > 0 && importStatus === 'idle' && (
          <div style={{ marginBottom: '1.5rem' }}>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 8, fontWeight: 600 }}>
              {folders.length} patient folder{folders.length !== 1 ? 's' : ''} found
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {folders.map(f => (
                <span key={f} style={{
                  padding: '3px 9px',
                  borderRadius: 4,
                  background: 'var(--bg-elevated)',
                  border: '1px solid var(--border)',
                  fontSize: 11,
                  fontFamily: 'monospace',
                  color: 'var(--text-secondary)',
                }}>
                  {f}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Import progress log */}
        {(isRunning || isDone || importStatus === 'error') && log.length > 0 && (
          <div style={{
            marginBottom: '1.5rem',
            maxHeight: 180,
            overflowY: 'auto',
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border)',
            borderRadius: 6,
            padding: '0.65rem 0.75rem',
            fontFamily: 'monospace',
            fontSize: 12,
          }}>
            {log.map((entry, i) => (
              <div key={i} style={{
                color: entry.status === 'error' ? 'var(--danger)'
                  : entry.status === 'skipped' ? 'var(--text-secondary)'
                  : 'var(--success)',
                marginBottom: 2,
              }}>
                {entry.status === 'copied'  && `✓ ${entry.folder}`}
                {entry.status === 'skipped' && `— ${entry.folder} (already in inbox)`}
                {entry.status === 'error'   && `✗ ${entry.folder}: ${entry.message}`}
              </div>
            ))}
            {isRunning && (
              <div style={{ color: 'var(--text-secondary)', marginTop: 4 }}>Copying...</div>
            )}
          </div>
        )}

        {/* Actions */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {importStatus === 'idle' && (
            <button
              onClick={startImport}
              disabled={scanStatus !== 'ready' || folders.length === 0}
              style={{
                ...btnPrimary,
                opacity: scanStatus === 'ready' && folders.length > 0 ? 1 : 0.45,
                cursor: scanStatus === 'ready' && folders.length > 0 ? 'pointer' : 'not-allowed',
              }}
            >
              Import {folders.length > 0 ? `${folders.length} patient${folders.length !== 1 ? 's' : ''}` : 'patients'} to workspace
            </button>
          )}

          {isRunning && (
            <button disabled style={{ ...btnPrimary, opacity: 0.6, cursor: 'not-allowed', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
              <span style={{
                width: 14, height: 14,
                border: '2px solid rgba(255,255,255,0.3)',
                borderTopColor: '#fff',
                borderRadius: '50%',
                display: 'inline-block',
                animation: 'spin 0.7s linear infinite',
              }} />
              Importing...
            </button>
          )}

          <button
            onClick={skipImport}
            disabled={isRunning}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-secondary)',
              fontSize: 13,
              cursor: isRunning ? 'not-allowed' : 'pointer',
              padding: '0.4rem 0',
              textDecoration: 'underline',
              textAlign: 'center',
            }}
          >
            Skip — I already have files in the inbox
          </button>
        </div>
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
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

const btnPrimary = {
  width: '100%',
  padding: '0.75rem',
  borderRadius: 8,
  border: 'none',
  background: 'var(--accent)',
  color: '#fff',
  fontSize: 14,
  fontWeight: 600,
  transition: 'opacity 0.15s',
};
