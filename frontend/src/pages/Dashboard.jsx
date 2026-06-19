import { useState, useEffect } from 'react';
import { api } from '../services/api';
import { Cpu, FolderOpen, Plus, Clock, CheckCircle2, AlertCircle, Zap } from 'lucide-react';
import './Dashboard.css';

export default function Dashboard({ onProjectOpen }) {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [projectName, setProjectName] = useState('');
  const [projectPrompt, setProjectPrompt] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');
  const [backendOnline, setBackendOnline] = useState(null);
  const [llmProvider, setLlmProvider] = useState('ollama');
  const [availableModels, setAvailableModels] = useState([]);
  const [activeModel, setActiveModel] = useState('');

  useEffect(() => {
    loadProjects();
    checkHealth();
  }, []);

  async function checkHealth() {
    try {
      const data = await api.health();
      setBackendOnline(data.ollama?.ollama_running ?? false);
      setLlmProvider(data.ollama?.llm_provider || 'ollama');
      setAvailableModels(data.ollama?.available_models || []);
      setActiveModel(data.ollama?.model_name || '');
    } catch {
      setBackendOnline(false);
      setLlmProvider('unknown');
    }
  }

  async function loadProjects() {
    try {
      const data = await api.listProjects();
      setProjects(data.projects || []);
    } catch (err) {
      setError('Cannot connect to backend. Make sure the server is running.');
    } finally {
      setLoading(false);
    }
  }

  async function handleModelChange(e) {
    const newModel = e.target.value;
    setActiveModel(newModel);
    try {
      await api.updateModel(newModel);
      await checkHealth(); // Refresh status
    } catch (err) {
      console.error("Failed to update model", err);
    }
  }

  async function handleCreate(e) {
    e.preventDefault();
    if (!projectName.trim()) return;

    setCreating(true);
    setError('');
    try {
      const data = await api.createProject(projectName.trim(), projectPrompt.trim());
      onProjectOpen(data.project);
    } catch (err) {
      setError(err.message);
    } finally {
      setCreating(false);
    }
  }

  async function handleLoadProject(project) {
    setError('');
    try {
      const data = await api.loadProject(project.workspace_path);
      onProjectOpen(data.project);
    } catch (err) {
      setError(err.message);
    }
  }

  function getStatusIcon(status) {
    switch (status) {
      case 'completed': return <CheckCircle2 size={16} className="status-icon completed" />;
      case 'failed': return <AlertCircle size={16} className="status-icon failed" />;
      case 'executing': return <Zap size={16} className="status-icon executing" />;
      default: return <Clock size={16} className="status-icon pending" />;
    }
  }

  const providerName = llmProvider === 'gemini' ? 'Gemini' : llmProvider === 'groq' ? 'Groq' : 'Ollama';

  return (
    <div className="dashboard">
      {/* Header */}
      <header className="dashboard-header">
        <div className="header-content">
          <div className="logo-section">
            <div className="logo-icon">
              <Cpu size={28} />
            </div>
            <div>
              <h1>Context Agent</h1>
              <p className="tagline">AI-Powered Coding Assistant</p>
            </div>
          </div>
          <div className="header-status">
            {llmProvider === 'groq' && availableModels.length > 0 && (
              <select 
                className="model-select input" 
                value={activeModel} 
                onChange={handleModelChange}
                disabled={!backendOnline}
                style={{ marginRight: '1rem', padding: '0.25rem 0.5rem', width: 'auto' }}
              >
                {availableModels.map(m => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            )}
            <span className={`status-dot ${backendOnline === true ? 'online' : backendOnline === false ? 'offline' : 'checking'}`} />
            <span className="status-text">
              {backendOnline === null ? 'Checking...' : backendOnline ? `${providerName} Connected` : `${providerName} Offline`}
            </span>
          </div>
        </div>
      </header>

      <main className="dashboard-main">
        {error && (
          <div className="error-banner animate-fade-in">
            <AlertCircle size={18} />
            <span>{error}</span>
            <button onClick={() => setError('')} className="btn-ghost btn-sm">✕</button>
          </div>
        )}

        {/* Create Project Section */}
        <section className="create-section animate-fade-in">
          {!showCreate ? (
            <button className="create-button" onClick={() => setShowCreate(true)} id="create-project-btn">
              <div className="create-button-icon">
                <Plus size={24} />
              </div>
              <div className="create-button-text">
                <span className="create-title">New Project</span>
                <span className="create-subtitle">Start building something amazing</span>
              </div>
            </button>
          ) : (
            <form className="create-form glass-panel" onSubmit={handleCreate}>
              <h2>Create New Project</h2>
              <div className="form-group">
                <label htmlFor="project-name">Project Name</label>
                <input
                  id="project-name"
                  type="text"
                  className="input"
                  placeholder="e.g., Calculator App"
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  autoFocus
                  required
                />
              </div>
              <div className="form-group">
                <label htmlFor="project-prompt">Project Description <span className="optional">(optional — you can add this later)</span></label>
                <textarea
                  id="project-prompt"
                  className="textarea"
                  placeholder="Describe the system you want to build. Be specific about features, data structures, and expected behavior..."
                  value={projectPrompt}
                  onChange={(e) => setProjectPrompt(e.target.value)}
                  rows={5}
                />
              </div>
              <div className="form-actions">
                <button type="button" className="btn btn-secondary" onClick={() => setShowCreate(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={creating || !projectName.trim()} id="submit-project-btn">
                  {creating ? 'Creating...' : 'Create Project'}
                </button>
              </div>
            </form>
          )}
        </section>

        {/* Projects List */}
        <section className="projects-section">
          <h2 className="section-title">
            <FolderOpen size={20} />
            Your Projects
          </h2>

          {loading ? (
            <div className="loading-state">
              <div className="spinner" />
              <p>Loading projects...</p>
            </div>
          ) : projects.length === 0 ? (
            <div className="empty-state glass-panel">
              <Cpu size={48} className="empty-icon" />
              <h3>No projects yet</h3>
              <p>Create your first project to get started with the AI coding agent.</p>
            </div>
          ) : (
            <div className="projects-grid">
              {projects.map((project, idx) => (
                <button
                  key={project.project_id || idx}
                  className="project-card glass-panel animate-fade-in"
                  style={{ animationDelay: `${idx * 0.05}s` }}
                  onClick={() => handleLoadProject(project)}
                  id={`project-card-${idx}`}
                >
                  <div className="card-header">
                    <h3 className="card-title truncate">{project.project_name || 'Untitled'}</h3>
                    {getStatusIcon(project.status)}
                  </div>
                  <div className="card-meta">
                    <span className="card-status">{project.status || 'idle'}</span>
                    <span className="card-sep">•</span>
                    <span>{project.completed_steps}/{project.total_steps} steps</span>
                  </div>
                  {project.progress > 0 && (
                    <div className="card-progress">
                      <div className="progress-bar">
                        <div className="progress-fill" style={{ width: `${project.progress}%` }} />
                      </div>
                      <span className="progress-text">{project.progress}%</span>
                    </div>
                  )}
                  {project.created_at && (
                    <div className="card-date">
                      {new Date(project.created_at).toLocaleDateString()}
                    </div>
                  )}
                </button>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
