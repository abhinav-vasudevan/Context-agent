import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../services/api';
import { useWebSocket } from '../hooks/useWebSocket';
import PlanPanel from '../components/PlanPanel';
import CodeViewer from '../components/CodeViewer';
import OutputPanel from '../components/OutputPanel';
import LLMStream from '../components/LLMStream';
import PermissionModal from '../components/PermissionModal';
import InputModal from '../components/InputModal';
import { ArrowLeft, Play, Send, Cpu, FileCode, Terminal, Brain, FolderTree, Square } from 'lucide-react';
import './Workspace.css';

export default function Workspace({ projectData, onBack }) {
  // ── State ──────────────────────────────────────────────────────────
  const [project, setProject] = useState(projectData);
  const [prompt, setPrompt] = useState(projectData?.original_prompt || '');
  const [planSteps, setPlanSteps] = useState(projectData?.plan_steps || []);
  const [status, setStatus] = useState(projectData?.status || 'idle');
  const [statusDetail, setStatusDetail] = useState('');
  const [activePanel, setActivePanel] = useState('plan');
  const [followupText, setFollowupText] = useState('');

  // LLM stream
  const [llmText, setLlmText] = useState('');
  const [llmStreaming, setLlmStreaming] = useState(false);

  // Process output
  const [processOutput, setProcessOutput] = useState([]);
  const [processRunning, setProcessRunning] = useState(false);

  // Code viewer
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileContent, setFileContent] = useState('');
  const [workspaceFiles, setWorkspaceFiles] = useState([]);

  // Permission modal
  const [permissionRequest, setPermissionRequest] = useState(null);

  // Input modal
  const [inputRequest, setInputRequest] = useState(null);

  // Model settings
  const [llmProvider, setLlmProvider] = useState('ollama');
  const [availableModels, setAvailableModels] = useState([]);
  const [activeModel, setActiveModel] = useState('');

  // Track if user manually clicked a tab — prevents auto-switching
  const userSelectedPanelRef = useRef(false);
  // Track the current llmText length to detect "first token"
  const llmTextRef = useRef('');

  // Wrapper that marks panel switches as user-initiated
  function handleUserTabClick(panel) {
    userSelectedPanelRef.current = true;
    setActivePanel(panel);
  }

  // ── WebSocket ──────────────────────────────────────────────────────
  const ws = useWebSocket({
    llm_token: (data) => {
      setLlmStreaming(true);
      setLlmText(prev => prev + data.token);
      // Only auto-switch to AI Output on the FIRST token of a new generation
      // AND only if the user hasn't manually picked a different tab
      if (!userSelectedPanelRef.current && llmTextRef.current === '') {
        setActivePanel('llm');
      }
      llmTextRef.current += data.token;
    },
    llm_done: (data) => {
      setLlmStreaming(false);
    },
    process_stdout: (data) => {
      setProcessOutput(prev => {
        if (prev.length > 0 && prev[prev.length - 1].type === 'stdout') {
          const newPrev = [...prev];
          newPrev[newPrev.length - 1] = { 
            ...newPrev[newPrev.length - 1], 
            text: newPrev[newPrev.length - 1].text + data.text 
          };
          return newPrev;
        }
        return [...prev, { type: 'stdout', text: data.text }];
      });
      setProcessRunning(true);
      // Auto-detect input requests from stdout
      const text = data.text.trim();
      if (text && (text.endsWith(':') || text.endsWith('?') || text.endsWith('> ') || text.includes('input'))) {
        setInputRequest({ prompt: text });
      }
    },
    process_stderr: (data) => {
      setProcessOutput(prev => {
        if (prev.length > 0 && prev[prev.length - 1].type === 'stderr') {
          const newPrev = [...prev];
          newPrev[newPrev.length - 1] = { 
            ...newPrev[newPrev.length - 1], 
            text: newPrev[newPrev.length - 1].text + data.text 
          };
          return newPrev;
        }
        return [...prev, { type: 'stderr', text: data.text }];
      });
    },
    process_done: (data) => {
      setProcessRunning(false);
      setInputRequest(null);
    },
    input_request: (data) => {
      setInputRequest({ prompt: data.prompt });
      // Only auto-switch to output for input requests (user needs to respond)
      if (!userSelectedPanelRef.current) {
        setActivePanel('output');
      }
    },
    status: (data) => {
      setStatus(data.status);
      setStatusDetail(data.detail || '');

      if (data.status === 'generating' || data.status === 'fixing' || data.status === 'planning') {
        // New generation starting — reset the "user selected" flag and llm text
        setLlmText('');
        setLlmStreaming(true);
        userSelectedPanelRef.current = false;
        llmTextRef.current = '';
      }
      if (data.status === 'running') {
        setProcessRunning(true);
        // Do NOT force-switch to output tab — let the user stay where they are
      }
    },
    step_update: (data) => {
      setPlanSteps(prev => prev.map(step =>
        step.step_number === data.step_number
          ? { ...step, status: data.status }
          : step
      ));
    },
    plan_update: (data) => {
      setPlanSteps(data.steps);
      // Only auto-switch to plan if user hasn't picked a tab
      if (!userSelectedPanelRef.current) {
        setActivePanel('plan');
      }
    },
    permission_request: (data) => {
      setPermissionRequest(data);
    },
    file_update: (data) => {
      if (selectedFile === data.file_path || !selectedFile) {
        setSelectedFile(data.file_path);
        setFileContent(data.content);
      }
      // Refresh file list
      loadFiles();
    },
    error: (data) => {
      setStatusDetail(data.error);
    },
    pong: () => {},
  });

  // ── Load files ─────────────────────────────────────────────────────
  async function loadFiles() {
    try {
      const data = await api.listFiles();
      setWorkspaceFiles(data.files || []);
    } catch {}
  }

  async function loadFileContent(filePath) {
    try {
      const data = await api.getFile(filePath);
      setSelectedFile(filePath);
      setFileContent(data.content || '');
      setActivePanel('code');
    } catch {}
  }

  useEffect(() => {
    if (project) {
      loadFiles();
      // If project already has steps, show them
      if (project.plan_steps?.length) {
        setPlanSteps(project.plan_steps);
      }
    }
    checkHealth();
  }, [project]);

  async function checkHealth() {
    try {
      const data = await api.health();
      setLlmProvider(data.ollama?.llm_provider || 'ollama');
      setAvailableModels(data.ollama?.available_models || []);
      setActiveModel(data.ollama?.model_name || '');
    } catch {
      setLlmProvider('unknown');
    }
  }

  async function handleModelChange(e) {
    const newModel = e.target.value;
    setActiveModel(newModel);
    try {
      await api.updateModel(newModel);
      await checkHealth();
    } catch (err) {
      console.error("Failed to update model", err);
    }
  }

  // ── Actions ────────────────────────────────────────────────────────
  async function handleGeneratePlan() {
    if (!prompt.trim()) return;
    setLlmText('');
    try {
      await api.generatePlan(prompt);
    } catch (err) {
      setStatusDetail(err.message);
    }
  }

  async function handleApprovePlan() {
    try {
      await api.approvePlan();
      setStatus('approved');
    } catch (err) {
      setStatusDetail(err.message);
    }
  }

  async function handleExecuteNext() {
    const nextStep = planSteps.find(s => s.status === 'pending' || s.status === 'failed');
    if (!nextStep) return;
    
    try {
      await api.executeStep(nextStep.step_number);
    } catch (err) {
      setStatusDetail(err.message);
    }
  }

  async function handleExecuteAll() {
    try {
      await api.executeAll();
    } catch (err) {
      setStatusDetail(err.message);
    }
  }

  async function handleSendInput(text) {
    setInputRequest(null);
    setProcessOutput(prev => [...prev, { type: 'input', text: text + '\n' }]);
    try {
      await api.sendInput(text);
    } catch (err) {
      console.error('Failed to send input:', err);
    }
  }

  async function handleFollowup() {
    if (!followupText.trim()) return;
    try {
      await api.projectFollowup(followupText);
      setFollowupText('');
    } catch (err) {
      setStatusDetail(err.message);
    }
  }

  async function handlePermissionResponse(granted) {
    setPermissionRequest(null);
    try {
      await api.respondPermission(granted);
    } catch (err) {
      console.error('Failed to respond permission:', err);
    }
  }

  async function handleKillProcess() {
    try {
      await api.killProcess();
      setProcessRunning(false);
      setInputRequest(null);
    } catch {}
  }

  // ── Status label ───────────────────────────────────────────────────
  function getStatusLabel() {
    const labels = {
      'idle': 'Ready',
      'setup': 'Setting Up',
      'planning': 'Planning',
      'plan_review': 'Plan Ready',
      'approved': 'Plan Approved',
      'executing': 'Executing',
      'generating': 'Generating Code',
      'integrating': 'Integrating',
      'running': 'Running',
      'fixing': 'Fixing Error',
      'fixed': 'Fixed',
      'completed': 'Completed',
      'paused': 'Paused',
      'cancelled': 'Cancelled',
      'warning': 'Warning',
      'ready': 'Ready',
    };
    return labels[status] || status;
  }

  function getStatusClass() {
    if (['completed', 'fixed', 'ready'].includes(status)) return 'success';
    if (['executing', 'generating', 'running', 'planning', 'fixing', 'integrating'].includes(status)) return 'active';
    if (['failed', 'cancelled'].includes(status)) return 'error';
    return 'default';
  }

  // ── Show prompt input if no prompt yet ─────────────────────────────
  const needsPrompt = !project?.plan_steps?.length && status !== 'planning' && status !== 'plan_review';

  return (
    <div className="workspace">
      {/* Permission Modal */}
      {permissionRequest && (
        <PermissionModal
          question={permissionRequest.question}
          defaultValue={permissionRequest.default}
          onResponse={handlePermissionResponse}
        />
      )}

      {/* Input Modal */}
      {inputRequest && (
        <InputModal
          prompt={inputRequest.prompt}
          onSubmit={handleSendInput}
          onCancel={() => setInputRequest(null)}
        />
      )}

      {/* Header */}
      <header className="workspace-header">
        <div className="header-left">
          <button className="btn btn-ghost" onClick={onBack} id="back-btn">
            <ArrowLeft size={18} />
          </button>
          <div className="project-info">
            <h1 className="project-title">{project?.project_name || 'Project'}</h1>
            <div className={`project-status ${getStatusClass()}`}>
              <span className="status-indicator" />
              {getStatusLabel()}
            </div>
          </div>
        </div>
        <div className="header-right" style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          {llmProvider === 'groq' && availableModels.length > 0 && (
            <select 
              className="model-select input" 
              value={activeModel} 
              onChange={handleModelChange}
              style={{ padding: '0.25rem 0.5rem', width: 'auto', backgroundColor: 'var(--bg-card)' }}
            >
              {availableModels.map(m => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
          )}
          <span className={`ws-indicator ${ws.connected ? 'connected' : ''}`}>
            {ws.connected ? '● Live' : '○ Connecting'}
          </span>
        </div>
      </header>

      {/* Prompt Input (shown when no plan exists) */}
      {needsPrompt && (
        <div className="prompt-section animate-fade-in">
          <div className="prompt-card glass-panel">
            <h2>What would you like to build?</h2>
            <p className="prompt-hint">Describe the system, features, and expected behavior in detail.</p>
            <textarea
              className="textarea prompt-textarea"
              placeholder="Build a calculator application with add, subtract, multiply, divide operations. It should have an interactive menu where the user can choose an operation, enter two numbers, see the result, and loop back to the menu..."
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={6}
              id="prompt-input"
            />
            <div className="prompt-actions">
              <button
                className="btn btn-primary btn-lg"
                onClick={handleGeneratePlan}
                disabled={!prompt.trim() || status === 'planning'}
                id="generate-plan-btn"
              >
                <Brain size={18} />
                {status === 'planning' ? 'Generating Plan...' : 'Generate Plan'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Action Bar (shown when plan exists) */}
      {planSteps.length > 0 && (
        <div className="action-bar">
          {status === 'plan_review' && (
            <button className="btn btn-success" onClick={handleApprovePlan} id="approve-plan-btn">
              <Play size={16} /> Approve & Execute
            </button>
          )}
          {['approved', 'paused'].includes(status) && (
            <>
              <button className="btn btn-primary" onClick={handleExecuteNext} id="execute-next-btn">
                <Play size={16} /> Execute Next Step
              </button>
              <button className="btn btn-secondary" onClick={handleExecuteAll} id="execute-all-btn">
                <Play size={16} /> Execute All
              </button>
            </>
          )}
          {processRunning && (
            <button className="btn btn-danger btn-sm" onClick={handleKillProcess} id="kill-process-btn">
              <Square size={14} /> Kill Process
            </button>
          )}
          {statusDetail && (
            <span className="status-detail">{statusDetail}</span>
          )}
        </div>
      )}

      {/* Main Panels */}
      {planSteps.length > 0 && (
        <div className="workspace-body">
          {/* Panel Tabs */}
          <nav className="panel-tabs">
            <button className={`tab ${activePanel === 'plan' ? 'active' : ''}`} onClick={() => handleUserTabClick('plan')} id="tab-plan">
              <FolderTree size={16} /> Plan
            </button>
            <button className={`tab ${activePanel === 'llm' ? 'active' : ''}`} onClick={() => handleUserTabClick('llm')} id="tab-llm">
              <Brain size={16} /> AI Output
              {llmStreaming && <span className="tab-pulse" />}
            </button>
            <button className={`tab ${activePanel === 'code' ? 'active' : ''}`} onClick={() => handleUserTabClick('code')} id="tab-code">
              <FileCode size={16} /> Code
            </button>
            <button className={`tab ${activePanel === 'output' ? 'active' : ''}`} onClick={() => handleUserTabClick('output')} id="tab-output">
              <Terminal size={16} /> Output
              {processRunning && <span className="tab-pulse green" />}
            </button>
          </nav>

          {/* Panel Content */}
          <div className="panel-content">
            {activePanel === 'plan' && (
              <PlanPanel
                steps={planSteps}
                files={workspaceFiles}
                onFileSelect={loadFileContent}
                planText={project?.plan_text || llmText}
              />
            )}
            {activePanel === 'llm' && (
              <LLMStream text={llmText} streaming={llmStreaming} />
            )}
            {activePanel === 'code' && (
              <CodeViewer
                filePath={selectedFile}
                content={fileContent}
                files={workspaceFiles}
                onFileSelect={loadFileContent}
              />
            )}
            {activePanel === 'output' && (
              <OutputPanel
                output={processOutput}
                running={processRunning}
                onSendInput={handleSendInput}
                onKill={handleKillProcess}
                onClear={() => setProcessOutput([])}
              />
            )}
          </div>
        </div>
      )}

      {/* Manual Error Fix / Followup — always visible so user can paste errors anytime */}
      {planSteps.length > 0 && (
        <div className="followup-section">
          <div className="followup-card glass-panel">
            <h3>Need to fix an error or add a feature?</h3>
            <p className="followup-hint">Paste your terminal error traceback or request changes here.</p>
            <div className="followup-input-group">
              <textarea
                className="textarea followup-textarea"
                placeholder="Paste traceback or describe changes..."
                value={followupText}
                onChange={(e) => setFollowupText(e.target.value)}
                rows={3}
              />
              <button 
                className="btn btn-primary" 
                onClick={handleFollowup}
                disabled={!followupText.trim()}
              >
                <Send size={16} /> Submit
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
