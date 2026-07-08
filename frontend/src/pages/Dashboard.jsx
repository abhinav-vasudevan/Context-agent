import { useState, useEffect } from 'react';
import { api } from '../services/api';
import { Cpu, FolderOpen, Plus, Clock, CheckCircle2, AlertCircle, Zap, Box } from 'lucide-react';

export default function Dashboard({ onProjectOpen }) {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState('none'); // 'none', 'create', 'ingest'
  const [projectName, setProjectName] = useState('');
  const [projectPrompt, setProjectPrompt] = useState('');
  const [codebasePath, setCodebasePath] = useState('');
  const [file, setFile] = useState(null);
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
    } catch {
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
      const data = await api.createProject(projectName.trim(), projectPrompt.trim(), mode, file);
      onProjectOpen(data.project);
    } catch (err) {
      setError(err.message);
    } finally {
      setCreating(false);
    }
  }

  async function handleIngest(e) {
    e.preventDefault();
    if (!projectName.trim() || !codebasePath.trim()) return;

    setCreating(true);
    setError('');
    try {
      const data = await api.ingestCodebase(projectName.trim(), codebasePath.trim());
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
      case 'completed': return <CheckCircle2 size={16} className="text-emerald-500" />;
      case 'failed': return <AlertCircle size={16} className="text-red-500" />;
      case 'executing': return <Zap size={16} className="text-amber-500" />;
      default: return <Clock size={16} className="text-nude-500" />;
    }
  }

  const providerName = llmProvider === 'gemini' ? 'Gemini' : llmProvider === 'groq' ? 'Groq' : 'Ollama';

  return (
    <div className="h-full flex flex-col bg-nude-900 text-nude-300 font-sans overflow-y-auto custom-scrollbar">
      {/* Header */}
      <header className="flex-none bg-nude-850 border-b border-nude-700 p-4 sticky top-0 z-10 shadow-sm">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="bg-nude-700/50 p-2.5 rounded-xl border border-nude-600/30 text-nude-200">
              <Cpu size={24} strokeWidth={1.5} />
            </div>
            <div>
              <h1 className="text-xl font-medium text-nude-100 tracking-wide">Context Agent</h1>
              <p className="text-xs text-nude-500 font-mono tracking-wider uppercase">AI-Powered Coding System</p>
            </div>
          </div>
          <div className="flex items-center gap-4 text-sm font-medium">
            {llmProvider === 'groq' && availableModels.length > 0 && (
              <select 
                className="bg-nude-800 border border-nude-700 rounded-lg px-3 py-1.5 text-nude-300 focus:outline-none focus:border-nude-500"
                value={activeModel} 
                onChange={handleModelChange}
                disabled={!backendOnline}
              >
                {availableModels.map(m => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            )}
            <div className="flex items-center gap-2 bg-nude-800/50 px-3 py-1.5 rounded-full border border-nude-700/50">
              <span className={`w-2 h-2 rounded-full ${backendOnline === true ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]' : backendOnline === false ? 'bg-red-500' : 'bg-nude-500 animate-pulse'}`} />
              <span className="text-xs tracking-wider uppercase text-nude-400">
                {backendOnline === null ? 'Checking...' : backendOnline ? `${providerName} Ready` : `${providerName} Offline`}
              </span>
            </div>
          </div>
        </div>
      </header>

      <main className="flex-1 max-w-6xl w-full mx-auto p-6 md:p-10 flex flex-col gap-10">
        {error && (
          <div className="flex items-center gap-3 bg-red-950/40 border border-red-900/50 text-red-400 p-4 rounded-xl">
            <AlertCircle size={18} />
            <span className="flex-1">{error}</span>
            <button onClick={() => setError('')} className="hover:text-red-300 transition-colors">✕</button>
          </div>
        )}

        {/* Create / Ingest Project Section */}
        <section className="flex flex-col gap-4">
          {mode === 'none' ? (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <button 
                className="group flex flex-col items-center justify-center p-8 bg-nude-850/50 hover:bg-nude-800 border border-nude-700 border-dashed rounded-2xl transition-all hover:border-nude-500"
                onClick={() => setMode('create')}
              >
                <div className="bg-nude-800 group-hover:bg-nude-700 p-4 rounded-full mb-4 transition-colors">
                  <Plus size={32} className="text-nude-400 group-hover:text-nude-200" />
                </div>
                <span className="text-lg font-medium text-nude-200 mb-1">Build from Scratch</span>
                <span className="text-sm text-nude-500 text-center px-4">Start fresh from a prompt or uploaded document</span>
              </button>
              <button 
                className="group flex flex-col items-center justify-center p-8 bg-nude-850/50 hover:bg-nude-800 border border-nude-700 border-dashed rounded-2xl transition-all hover:border-nude-500"
                onClick={() => setMode('ingest')}
              >
                <div className="bg-nude-800 group-hover:bg-nude-700 p-4 rounded-full mb-4 transition-colors">
                  <FolderOpen size={32} className="text-nude-400 group-hover:text-nude-200" />
                </div>
                <span className="text-lg font-medium text-nude-200 mb-1">Ingest Codebase</span>
                <span className="text-sm text-nude-500 text-center px-4">Import and modify an existing local codebase</span>
              </button>
              <button 
                className="group flex flex-col items-center justify-center p-8 bg-nude-850/50 hover:bg-nude-800 border border-nude-700 border-dashed rounded-2xl transition-all hover:border-nude-500"
                onClick={() => setMode('docs')}
              >
                <div className="bg-nude-800 group-hover:bg-nude-700 p-4 rounded-full mb-4 transition-colors">
                  <Box size={32} className="text-nude-400 group-hover:text-nude-200" />
                </div>
                <span className="text-lg font-medium text-nude-200 mb-1">Docs Operations</span>
                <span className="text-sm text-nude-500 text-center px-4">Chat with and analyze documents only</span>
              </button>
            </div>
          ) : mode === 'create' || mode === 'docs' ? (
            <form className="bg-nude-850 border border-nude-700 rounded-2xl p-6 md:p-8 shadow-soft" onSubmit={handleCreate}>
              <h2 className="text-xl font-medium text-nude-100 mb-6 flex items-center gap-2">
                <Box size={20} className="text-nude-500" /> {mode === 'create' ? 'Initialize Workspace' : 'Docs Workspace'}
              </h2>
              
              <div className="space-y-6">
                <div>
                  <label htmlFor="project-name" className="block text-sm font-medium text-nude-400 mb-2">Workspace Name</label>
                  <input
                    id="project-name"
                    type="text"
                    className="w-full bg-nude-900 border border-nude-700 rounded-xl px-4 py-3 text-nude-200 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent transition-all placeholder:text-nude-600"
                    placeholder="e.g., semantic-search-engine"
                    value={projectName}
                    onChange={(e) => setProjectName(e.target.value)}
                    autoFocus
                    required
                  />
                </div>
                
                <div>
                  <label htmlFor="project-prompt" className="block text-sm font-medium text-nude-400 mb-2">
                    Initial Context <span className="text-nude-600 font-normal">(Optional)</span>
                  </label>
                  <textarea
                    id="project-prompt"
                    className="w-full bg-nude-900 border border-nude-700 rounded-xl px-4 py-3 text-nude-200 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent transition-all placeholder:text-nude-600 resize-y min-h-[120px]"
                    placeholder={mode === 'create' ? "Provide architecture guidelines, target goals, or specific tech stack details..." : "Provide instructions for how you want to analyze or chat with the documents..."}
                    value={projectPrompt}
                    onChange={(e) => setProjectPrompt(e.target.value)}
                  />
                </div>
                
                {mode === 'create' && (
                  <div>
                    <label htmlFor="project-file" className="block text-sm font-medium text-nude-400 mb-2">
                      Upload Document <span className="text-nude-600 font-normal">(Optional, e.g. plan.txt)</span>
                    </label>
                    <input
                      id="project-file"
                      type="file"
                      className="w-full bg-nude-900 border border-nude-700 rounded-xl px-4 py-3 text-nude-200 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent transition-all"
                      onChange={(e) => setFile(e.target.files[0])}
                    />
                    <p className="text-xs text-nude-500 mt-2">If provided, the system will immediately build the code based on this document.</p>
                  </div>
                )}

                <div className="flex items-center justify-end gap-3 pt-4 border-t border-nude-700/50">
                  <button type="button" className="px-6 py-2.5 rounded-xl text-nude-400 hover:text-nude-200 hover:bg-nude-800 transition-colors font-medium text-sm" onClick={() => setMode('none')}>
                    Cancel
                  </button>
                  <button 
                    type="submit" 
                    className="px-6 py-2.5 rounded-xl bg-nude-200 text-nude-900 hover:bg-white disabled:opacity-50 disabled:hover:bg-nude-200 transition-colors font-medium text-sm shadow-sm"
                    disabled={creating || !projectName.trim()}
                  >
                    {creating ? 'Initializing...' : 'Create Workspace'}
                  </button>
                </div>
              </div>
            </form>
          ) : (
            <form className="bg-nude-850 border border-nude-700 rounded-2xl p-6 md:p-8 shadow-soft" onSubmit={handleIngest}>
              <h2 className="text-xl font-medium text-nude-100 mb-6 flex items-center gap-2">
                <FolderOpen size={20} className="text-nude-500" /> Ingest Codebase
              </h2>
              
              <div className="space-y-6">
                <div>
                  <label htmlFor="project-name" className="block text-sm font-medium text-nude-400 mb-2">Workspace Name</label>
                  <input
                    id="project-name"
                    type="text"
                    className="w-full bg-nude-900 border border-nude-700 rounded-xl px-4 py-3 text-nude-200 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent transition-all placeholder:text-nude-600"
                    placeholder="e.g., legacy-ecommerce-platform"
                    value={projectName}
                    onChange={(e) => setProjectName(e.target.value)}
                    autoFocus
                    required
                  />
                </div>
                
                <div>
                  <label htmlFor="codebase-path" className="block text-sm font-medium text-nude-400 mb-2">
                    Absolute Directory Path
                  </label>
                  <input
                    id="codebase-path"
                    type="text"
                    className="w-full bg-nude-900 border border-nude-700 rounded-xl px-4 py-3 text-nude-200 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent transition-all placeholder:text-nude-600"
                    placeholder="/absolute/path/to/existing/codebase"
                    value={codebasePath}
                    onChange={(e) => setCodebasePath(e.target.value)}
                    required
                  />
                </div>

                <div className="flex items-center justify-end gap-3 pt-4 border-t border-nude-700/50">
                  <button type="button" className="px-6 py-2.5 rounded-xl text-nude-400 hover:text-nude-200 hover:bg-nude-800 transition-colors font-medium text-sm" onClick={() => setMode('none')}>
                    Cancel
                  </button>
                  <button 
                    type="submit" 
                    className="px-6 py-2.5 rounded-xl bg-nude-200 text-nude-900 hover:bg-white disabled:opacity-50 disabled:hover:bg-nude-200 transition-colors font-medium text-sm shadow-sm"
                    disabled={creating || !projectName.trim() || !codebasePath.trim()}
                  >
                    {creating ? 'Ingesting...' : 'Start Ingestion'}
                  </button>
                </div>
              </div>
            </form>
          )}
        </section>

        {/* Projects List */}
        <section className="flex flex-col gap-6">
          <div className="flex items-center gap-2 border-b border-nude-800 pb-4">
            <FolderOpen size={20} className="text-nude-500" />
            <h2 className="text-lg font-medium text-nude-200 tracking-wide">Recent Workspaces</h2>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-20 text-nude-500 gap-3">
              <div className="w-5 h-5 border-2 border-nude-500 border-t-transparent rounded-full animate-spin"></div>
              <span>Scanning directories...</span>
            </div>
          ) : projects.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center bg-nude-850/30 rounded-2xl border border-nude-800 border-dashed">
              <FolderOpen size={48} className="text-nude-700 mb-4" strokeWidth={1} />
              <h3 className="text-nude-300 font-medium mb-1">No active workspaces</h3>
              <p className="text-sm text-nude-500">Your projects will appear here once created.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {projects.map((project, idx) => (
                <button
                  key={project.project_id || idx}
                  className="flex flex-col items-start p-5 bg-nude-850 border border-nude-700 hover:border-nude-500 rounded-xl transition-all hover:-translate-y-1 hover:shadow-soft text-left group"
                  onClick={() => handleLoadProject(project)}
                >
                  <div className="w-full flex items-center justify-between mb-3">
                    <h3 className="font-mono text-nude-200 font-medium truncate pr-2 group-hover:text-nude-50 transition-colors">{project.project_name || 'Untitled'}</h3>
                    {getStatusIcon(project.status)}
                  </div>
                  
                  <div className="flex items-center gap-2 text-xs text-nude-500 font-mono mb-4 w-full">
                    <span className="uppercase tracking-widest">{project.status || 'idle'}</span>
                    <span className="text-nude-700">•</span>
                    <span>{project.completed_steps}/{project.total_steps}</span>
                  </div>

                  {project.progress > 0 && (
                    <div className="w-full mt-auto">
                      <div className="h-1 w-full bg-nude-800 rounded-full overflow-hidden">
                        <div className="h-full bg-accent transition-all duration-500" style={{ width: `${project.progress}%` }} />
                      </div>
                    </div>
                  )}
                  
                  {project.created_at && (
                    <div className="w-full text-right text-[10px] text-nude-600 mt-3 pt-3 border-t border-nude-700/50 uppercase tracking-widest">
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
