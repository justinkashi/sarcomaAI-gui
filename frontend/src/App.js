import React, { useEffect } from 'react';
import { AppProvider, useApp } from './context/AppContext';
import { initCornerstone } from './utils/initCornerstone';
import SetupWizard from './components/SetupWizard';
import ImportStep from './components/ImportStep';
import MainLayout from './components/MainLayout';

function AppInner() {
  const { isConfigured, isImportDone } = useApp();
  if (!isConfigured) return <SetupWizard />;
  if (!isImportDone) return <ImportStep />;
  return <MainLayout />;
}

function App() {
  useEffect(() => { initCornerstone(); }, []);
  return (
    <AppProvider>
      <AppInner />
    </AppProvider>
  );
}

export default App;
