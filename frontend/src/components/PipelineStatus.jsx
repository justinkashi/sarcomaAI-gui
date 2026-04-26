import React, { useEffect, useRef, useState } from 'react';
import { useApp } from '../context/AppContext';

const API = 'http://localhost:5050';

export default function PipelineStatus() {
  const { pipelineState, setPipelineState, pipelineLog } = useApp();
  const [exporting,    setExporting]    = useState(false);
  const [exportResult, setExportResult] = useState(''); // filename on success, error msg on fail

  const exportLedger = async () => {
    setExporting(true);
    setExportResult('');
    try {
      const res = await fetch(`${API}/api/export-ledger`, { method: 'POST' });
      if (!res.ok) {
        const text = await res.text();
        setExportResult(`Error: ${text || 'Export failed'}`);
        return;
      }
      const data = await res.json();
      setExportResult(`Saved: ${data.filename}`);
    } catch (e) {
      setExportResult(`Error: ${e.message || 'Export failed'}`);
    } finally {
      setExporting(false);
    }
  };
  const logRef = useRef(null);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [pipelineLog]);

  if (pipelineState === 'idle') return null;

  const titleMap = {
    running: 'Pipeline Running...',
    done: 'Pipeline Complete',
    error: 'Pipeline Failed',
  };

  const logColor = (type) => {
    if (type === 'error') return 'var(--danger)';
    if (type === 'success') return 'var(--success)';
    return 'var(--text-secondary)';
  };

  return (
    <div style={{
      position: 'fixed',
      bottom: 0,
      left: 0,
      right: 0,
      height: '40vh',
      background: 'var(--bg-surface)',
      borderTop: '1px solid var(--border)',
      display: 'flex',
      flexDirection: 'column',
      zIndex: 500,
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '0.6rem 1rem',
        borderBottom: '1px solid var(--border)',
        flexShrink: 0,
      }}>
        {pipelineState === 'running' && (
          <span style={{
            width: 14, height: 14,
            border: '2px solid rgba(91,142,244,0.3)',
            borderTopColor: 'var(--accent)',
            borderRadius: '50%',
            display: 'inline-block',
            animation: 'spin 0.7s linear infinite',
            flexShrink: 0,
          }} />
        )}
        {pipelineState === 'done' && (
          <span style={{ color: 'var(--success)', fontSize: 16, lineHeight: 1 }}>✓</span>
        )}
        {pipelineState === 'error' && (
          <span style={{ color: 'var(--danger)', fontSize: 16, lineHeight: 1 }}>✗</span>
        )}

        <span style={{ fontWeight: 600, fontSize: 14, flex: 1 }}>
          {titleMap[pipelineState]}
        </span>

        {pipelineState === 'done' && (
          <button
            onClick={exportLedger}
            disabled={exporting}
            style={{
              background: 'var(--accent)',
              border: 'none',
              borderRadius: 5,
              color: '#fff',
              padding: '3px 12px',
              cursor: exporting ? 'not-allowed' : 'pointer',
              fontSize: 12,
              fontWeight: 600,
              opacity: exporting ? 0.6 : 1,
            }}
          >
            {exporting ? 'Exporting...' : 'Export Ledger'}
          </button>
        )}

        {exportResult && (
          <span style={{
            fontSize: 11,
            color: exportResult.startsWith('Error') ? 'var(--danger)' : 'var(--success)',
            fontFamily: 'monospace',
          }}>
            {exportResult}
          </span>
        )}

        {pipelineState !== 'running' && (
          <button
            onClick={() => setPipelineState('idle')}
            style={{
              background: 'none',
              border: '1px solid var(--border)',
              borderRadius: 5,
              color: 'var(--text-secondary)',
              padding: '3px 10px',
              cursor: 'pointer',
              fontSize: 12,
            }}
          >
            Close
          </button>
        )}
      </div>

      <div
        ref={logRef}
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '0.75rem 1rem',
          fontFamily: 'monospace',
          fontSize: 12,
          lineHeight: 1.6,
        }}
      >
        {pipelineLog.map((entry, i) => (
          <div key={i} style={{ color: logColor(entry.type) }}>
            {entry.text}
          </div>
        ))}
        {pipelineLog.length === 0 && (
          <div style={{ color: 'var(--text-secondary)' }}>Starting pipeline...</div>
        )}
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
