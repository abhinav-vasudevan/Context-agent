import { useState, useCallback } from 'react';
import Dashboard from './pages/Dashboard';
import Workspace from './pages/Workspace';

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
    <div className="bg-nude-900 text-nude-300 font-sans h-screen w-screen overflow-hidden">
      {currentPage === 'dashboard' ? (
        <Dashboard onProjectOpen={navigateToWorkspace} />
      ) : (
        <Workspace projectData={projectData} onBack={navigateToDashboard} />
      )}
    </div>
  );
}

export default App;
