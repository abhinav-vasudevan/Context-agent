import { useState, useCallback } from 'react';
import Dashboard from './pages/Dashboard';
import Workspace from './pages/Workspace';
import './App.css';

function App() {
  const [currentPage, setCurrentPage] = useState('dashboard');
  const [projectData, setProjectData] = useState(null);

  const navigateToWorkspace = useCallback((data) => {
    setProjectData(data);
    setCurrentPage('workspace');
  }, []);

  const navigateToDashboard = useCallback(() => {
    setCurrentPage('dashboard');
    setProjectData(null);
  }, []);

  return (
    <div className="app">
      {currentPage === 'dashboard' ? (
        <Dashboard onProjectOpen={navigateToWorkspace} />
      ) : (
        <Workspace projectData={projectData} onBack={navigateToDashboard} />
      )}
    </div>
  );
}

export default App;
