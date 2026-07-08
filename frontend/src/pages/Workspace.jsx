import { useState, useEffect, useRef } from 'react';
import { api } from '../services/api';
import { useWebSocket } from '../hooks/useWebSocket';
import CodeViewer from '../components/CodeViewer';
import { Terminal, FolderTree, Cpu, ArrowLeft, Send, Sparkles, BookOpen, Paperclip, X, Code2, User, ListTodo, CheckCircle2, Activity, Square, RotateCcw, ChevronDown, ChevronRight } from 'lucide-react';
import ArchitectureGraph from '../components/ArchitectureGraph';

export default function Workspace({ projectData, onBack }) {
  // ── State ──────────────────────────────────────────────────────────
  const [project, setProject] = useState(projectData);
  const [prompt, setPrompt] = useState(projectData?.original_prompt || '');
  const [status, setStatus] = useState(projectData?.status || 'idle');
  const [statusDetail, setStatusDetail] = useState('');
  const [progress, setProgress] = useState(null);
  const [autoApprovePlan, setAutoApprovePlan] = useState(false);
  
  // Tabs
  const [activeTab, setActiveTab] = useState(projectData?.project_mode === 'docs' ? 'graph' : 'code'); // code or knowledge
  const [isTerminalOpen, setIsTerminalOpen] = useState(true);
  const [expandedEpics, setExpandedEpics] = useState({});

  const toggleEpic = (epicId) => {
    setExpandedEpics(prev => ({ ...prev, [epicId]: !prev[epicId] }));
  };

  // Chat History
  const [messages, setMessages] = useState([]);
  const [attachedFiles, setAttachedFiles] = useState([]);

  // LLM stream (current message)
  const [llmText, setLlmText] = useState('');
  const [llmStreaming, setLlmStreaming] = useState(false);
  const [thinkingText, setThinkingText] = useState('');
  const [isThinking, setIsThinking] = useState(false);

  // Process output
  const [processOutput, setProcessOutput] = useState([]);
  const [processRunning, setProcessRunning] = useState(false);

  // Code viewer
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileContent, setFileContent] = useState('');
  const [workspaceFiles, setWorkspaceFiles] = useState([]);

  // Refs for autoscroll
  const terminalRef = useRef(null);
  const chatRef = useRef(null);
  const currentLlmRef = useRef(null);
  const currentThinkingRef = useRef(null);

  // ── WebSocket ──────────────────────────────────────────────────────
  useWebSocket({
    llm_token: (data) => {
      setLlmStreaming(true);
      setIsThinking(false);
      setLlmText(prev => prev + data.token);
      scrollToBottom(chatRef);
      scrollToBottom(currentLlmRef);
    },
    llm_thinking: (data) => {
      setIsThinking(true);
      setThinkingText(prev => prev + data.token);
      scrollToBottom(chatRef);
      scrollToBottom(currentThinkingRef);
    },
    llm_done: () => {
      setLlmStreaming(false);
      setIsThinking(false);
      
      api.getProjectState().then(data => {
        if (data.project && data.project.chat_history) {
          setMessages(data.project.chat_history);
        }
      }).catch(err => console.error("Failed to sync chat history:", err));
      
      setLlmText('');
      setThinkingText('');
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
      scrollToBottom(terminalRef);
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
      scrollToBottom(terminalRef);
    },
    process_done: () => {
      setProcessRunning(false);
    },
    status: (data) => {
      setStatus(data.status);
      setStatusDetail(data.detail || '');
      if (data.status === 'idle' || data.status === 'completed' || data.status === 'error') {
        setProgress(null);
      }
    },
    progress: (data) => {
      setProgress(data);
    },
    file_update: (data) => {
      loadFiles();
      if (data.file_path === selectedFile) {
        loadFileContent(data.file_path);
      }
    },
    step_update: (data) => {
      setProject(prev => {
        if (!prev) return prev;
        const newSteps = [...(prev.plan_steps || [])];
        const stepIdx = newSteps.findIndex(s => s.step_number === data.step_number);
        if (stepIdx !== -1) {
          newSteps[stepIdx] = { ...newSteps[stepIdx], status: data.status, summary: data.summary };
        }
        return { ...prev, plan_steps: newSteps };
      });
    },
    plan_update: (data) => {
      setProject(prev => {
        if (!prev) return prev;
        return { ...prev, plan_steps: data.steps || data };
      });
    },
    error: (data) => {
      console.error(data.error);
    },
    pong: () => {},
  });

  const scrollToBottom = (ref, force = false) => {
    if (ref.current) {
      if (force) {
        ref.current.scrollTop = ref.current.scrollHeight;
        return;
      }
      const { scrollTop, scrollHeight, clientHeight } = ref.current;
      const isNearBottom = scrollHeight - scrollTop - clientHeight < 150;
      if (isNearBottom) {
        ref.current.scrollTop = ref.current.scrollHeight;
      }
    }
  };

  async function loadFiles() {
    try {
      const data = await api.listFiles();
      setWorkspaceFiles(data.files || []);
    } catch (e) {
      console.error(e);
    }
  }

  async function loadFileContent(filePath) {
    try {
      const data = await api.getFile(filePath);
      setSelectedFile(filePath);
      setFileContent(data.content || '');
    } catch (e) {
      console.error(e);
    }
  }

  useEffect(() => {
    if (project) {
      loadFiles();
      setTimeout(() => {
        if (projectData && projectData.chat_history && projectData.chat_history.length > 0) {
          setMessages(projectData.chat_history);
        } else if (project.original_prompt && messages.length === 0) {
          setMessages([{ role: 'user', content: project.original_prompt }]);
        }
      }, 0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project, projectData]);

  useEffect(() => {
    if (status === 'plan_review') {
      if (autoApprovePlan) {
        api.approvePlan().then(() => api.executeAll());
      } else {
        setTimeout(() => setActiveTab('plan'), 0);
      }
    }
  }, [status, autoApprovePlan]);

  const handleSendPrompt = (e) => {
    e.preventDefault();
    if (!prompt.trim() && attachedFiles.length === 0) return;

    // Add user message to history
    setMessages(prev => [...prev, { role: 'user', content: prompt.trim() || 'Attached documents.' }]);

    // Clear chat streaming state for new prompt
    setLlmText('');
    setThinkingText('');

    // Determine whether to plan or follow-up
    const hasExistingPlan = project?.plan_steps && project.plan_steps.length > 0;

    if (hasExistingPlan || attachedFiles.length > 0) {
      api.projectFollowup(prompt.trim() || 'Please process the attached documents.', attachedFiles)
        .then(() => loadFiles())
        .catch(console.error);
    } else {
      api.generatePlan(prompt.trim(), attachedFiles).then((res) => {
        if (res.success) {
          if (res.project) {
            setProject(res.project);
          } else if (res.plan_steps) {
            setProject(prev => ({ ...prev, plan_steps: res.plan_steps }));
          }
        }
        loadFiles();
      }).catch(console.error);
    }

    setPrompt('');
    setAttachedFiles([]);
    setTimeout(() => scrollToBottom(chatRef, true), 100);
  };

  const formatAgentMessage = (text) => {
    if (!text) return null;
    let formatted = text.replace(/<view_file>(.*?)<\/view_file>/g, '\n👁️ Viewing: $1\n');
    formatted = formatted.replace(/<edit_file path="([^"]+)">[\s\S]*?(?:<\/edit_file>|$)/g, '\n📝 Editing: $1\n');
    formatted = formatted.replace(/<run_command>([\s\S]*?)<\/run_command>/g, '\n💻 Running Command: $1\n');
    return formatted;
  };

  const renderMessage = (msg, index) => {
    if (msg.role === 'user') {
      return (
        <div key={index} className="flex gap-3 my-4">
          <div className="w-6 h-6 rounded bg-nude-700 border border-nude-600 flex-shrink-0 flex items-center justify-center text-nude-200 mt-1">
            <User size={12} />
          </div>
          <div className="flex-1 text-sm text-nude-200 font-sans pt-1">
            {msg.content}
          </div>
        </div>
      );
    }
    
    return (
      <div key={index} className="flex flex-col gap-2 my-4">
        {msg.thinking && (
          <details className="group border border-nude-800 bg-nude-900/50 rounded-lg overflow-hidden ml-9">
            <summary className="text-xs text-nude-500 font-mono p-2 cursor-pointer hover:bg-nude-800 transition-colors select-none list-none flex items-center gap-2">
              <span className="group-open:rotate-90 transition-transform text-nude-600">▶</span>
              Thinking Process
            </summary>
            <div className="p-3 text-xs text-nude-500 font-mono whitespace-pre-wrap border-t border-nude-800">
              {msg.thinking}
            </div>
          </details>
        )}
        {msg.content && (
          <div className="flex gap-3">
            <div className="w-6 h-6 rounded bg-nude-800 border border-nude-700 flex-shrink-0 flex items-center justify-center text-accent mt-1">
              <Sparkles size={12} />
            </div>
            <div className="flex-1 text-xs text-nude-300 font-mono pt-1 whitespace-pre-wrap max-h-[350px] overflow-y-auto custom-scrollbar bg-nude-900/50 p-3 rounded-lg border border-nude-800/80 shadow-inner-soft">
              {formatAgentMessage(msg.content)}
            </div>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="h-screen w-screen flex flex-col bg-nude-900 text-nude-300 font-sans overflow-hidden">
      {/* Header */}
      <header className="h-12 border-b border-nude-700 bg-nude-850 flex items-center justify-between px-4 shrink-0">
        <div className="flex items-center gap-4">
          <button onClick={onBack} className="p-1 hover:bg-nude-700 rounded-md transition-colors text-nude-400 hover:text-nude-200">
            <ArrowLeft size={18} />
          </button>
          <div className="flex items-center gap-2 text-nude-200">
            <Cpu size={16} className="text-accent" />
            <span className="font-medium text-sm font-mono tracking-wide">{project?.project_name || 'Workspace'}</span>
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs font-mono uppercase tracking-widest text-nude-500">
          <label className="flex items-center gap-2 cursor-pointer hover:text-nude-300 transition-colors bg-nude-850 px-2 py-1 rounded-md border border-nude-700 select-none">
            <input 
              type="checkbox" 
              className="accent-accent cursor-pointer"
              checked={autoApprovePlan}
              onChange={(e) => setAutoApprovePlan(e.target.checked)}
            />
            <span className={autoApprovePlan ? "text-accent" : ""}>Auto-Approve Plan</span>
          </label>
          {status !== 'idle' && (
            <span className="flex items-center gap-2 bg-nude-800 px-2 py-1 rounded-md border border-nude-700">
              <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse"></span>
              {status} {statusDetail && <span className="text-nude-400 normal-case tracking-normal ml-1 border-l border-nude-700 pl-2">({statusDetail})</span>}
            </span>
          )}
        </div>
      </header>

      <div className="flex-1 flex overflow-hidden">
        {/* Left Sidebar: File Explorer */}
        <aside className="w-64 border-r border-nude-700 bg-nude-850 flex flex-col shrink-0">
          <div className="p-3 border-b border-nude-700/50 flex items-center gap-2 text-xs font-mono uppercase tracking-widest text-nude-500">
            <FolderTree size={14} /> Explorer
          </div>
          <div className="flex-1 overflow-y-auto custom-scrollbar p-2">
            {workspaceFiles.length === 0 ? (
              <div className="text-xs text-nude-500 italic p-4 text-center font-mono">Empty directory</div>
            ) : (
              workspaceFiles.map(file => (
                <button 
                  key={file} 
                  className={`w-full text-left flex items-center gap-2 p-1.5 px-3 rounded-md transition-colors text-sm font-mono ${selectedFile === file ? 'bg-nude-700 text-nude-100 shadow-inner-soft' : 'hover:bg-nude-800 text-nude-400 hover:text-nude-200'}`}
                  onClick={() => loadFileContent(file)}
                >
                  <Code2 size={14} className={selectedFile === file ? 'text-accent' : 'text-nude-500'} />
                  <span className="truncate" title={file}>{file}</span>
                </button>
              ))
            )}
          </div>
        </aside>

        {/* Center Canvas */}
        <main className="flex-1 flex flex-col min-w-0 bg-nude-900 relative">
          
          {/* Global Project Progress Bar */}
          {(() => {
            let globalProgressPercent = 0;
            if (project?.epic_queue && project.epic_queue.length > 0) {
              let completedEpicsCount = 0;
              project.epic_queue.forEach(epic => {
                const epicSteps = (project?.plan_steps || []).filter(s => s.epic_id === epic.id);
                if (epicSteps.length > 0 && epicSteps.every(s => s.status === 'completed')) {
                  completedEpicsCount++;
                }
              });
              globalProgressPercent = Math.round((completedEpicsCount / project.epic_queue.length) * 100);
            } else if (project?.plan_steps && project.plan_steps.length > 0) {
              globalProgressPercent = Math.round((project.plan_steps.filter(s => s.status === 'completed').length / project.plan_steps.length) * 100);
            }
            
            if (project?.epic_queue?.length > 0 || project?.plan_steps?.length > 0) {
              return (
                <div className="bg-nude-850 border-b border-nude-700 px-4 py-2 shrink-0">
                  <div className="flex justify-between items-center text-xs font-mono mb-1 text-nude-400">
                    <span>Project Progress</span>
                    <span>{globalProgressPercent}%</span>
                  </div>
                  <div className="w-full bg-nude-800 rounded-full h-1.5 overflow-hidden shadow-inner-soft">
                    <div 
                      className="bg-accent h-1.5 rounded-full transition-all duration-300 ease-out shadow-[0_0_10px_rgba(16,185,129,0.5)]" 
                      style={{ width: `${globalProgressPercent}%` }}
                    ></div>
                  </div>
                </div>
              );
            }
            return null;
          })()}

          {progress && (
            <div className="bg-nude-850 border-b border-nude-700 p-4 shrink-0 shadow-sm relative overflow-hidden">
              <div className="absolute inset-0 bg-accent/5"></div>
              <div className="relative z-10 flex flex-col gap-2">
                <div className="flex justify-between items-center text-xs font-mono">
                  <span className="text-accent uppercase tracking-widest flex items-center gap-2">
                    <Activity size={14} className="animate-pulse" /> Working...
                  </span>
                  <span className="text-nude-200">{Math.round(progress.percent || 0)}%</span>
                </div>
                <div className="w-full bg-nude-800 rounded-full h-2 overflow-hidden shadow-inner-soft">
                  <div 
                    className="bg-accent h-2 rounded-full transition-all duration-300 ease-out shadow-[0_0_10px_rgba(16,185,129,0.5)]" 
                    style={{ width: `${Math.max(0, Math.min(100, progress.percent || 0))}%` }}
                  ></div>
                </div>
                <div className="text-[10px] text-nude-500 font-mono text-center truncate px-2">
                  {progress.label || 'Processing...'}
                </div>
              </div>
            </div>
          )}

          <div className="flex h-10 border-b border-nude-700 bg-nude-850 shrink-0">
            {project?.project_mode !== 'docs' && (
              <>
                <button 
                  className={`px-4 flex items-center gap-2 border-r border-nude-700 text-xs font-mono uppercase tracking-widest transition-all ${activeTab === 'plan' ? 'bg-nude-900 text-nude-200 border-t-2 border-t-accent' : 'text-nude-500 hover:bg-nude-800 hover:text-nude-300 border-t-2 border-t-transparent'}`} 
                  onClick={() => setActiveTab('plan')}
                >
                  <ListTodo size={14} /> Plan
                </button>
                <button 
                  className={`px-4 flex items-center gap-2 border-r border-nude-700 text-xs font-mono uppercase tracking-widest transition-all ${activeTab === 'code' ? 'bg-nude-900 text-nude-200 border-t-2 border-t-accent' : 'text-nude-500 hover:bg-nude-800 hover:text-nude-300 border-t-2 border-t-transparent'}`} 
                  onClick={() => setActiveTab('code')}
                >
                  <Code2 size={14} /> Source Code
                </button>
              </>
            )}
            <button 
              className={`px-4 flex items-center gap-2 border-r border-nude-700 text-xs font-mono uppercase tracking-widest transition-all ${activeTab === 'graph' ? 'bg-nude-900 text-nude-200 border-t-2 border-t-accent' : 'text-nude-500 hover:bg-nude-800 hover:text-nude-300 border-t-2 border-t-transparent'}`} 
              onClick={() => setActiveTab('graph')}
            >
              <BookOpen size={14} /> {project?.project_mode === 'docs' ? 'Documents' : 'Knowledge'}
            </button>
          </div>
          
          <div className="flex-1 overflow-hidden relative">
            {/* Plan Tab */}
            <div className={`absolute inset-0 bg-nude-900 transition-opacity duration-200 p-8 ${activeTab === 'plan' ? 'opacity-100 z-10 overflow-y-auto custom-scrollbar' : 'opacity-0 z-0 pointer-events-none'}`}>
              <div className="max-w-3xl mx-auto pb-12">
                <div className="flex items-center justify-between mb-8">
                  <h2 className="text-2xl font-semibold text-nude-200 flex items-center gap-3">
                    <ListTodo className="text-accent" /> Implementation Plan
                  </h2>
                  <div className="flex items-center gap-3">
                    {status === 'paused' && (
                      <div className="flex gap-2">
                        <button
                          onClick={async () => {
                            await api.resumeExecution();
                          }}
                          className="px-5 py-2.5 bg-accent hover:bg-accent/80 text-nude-900 font-semibold text-sm rounded-lg shadow-[0_0_15px_rgba(16,185,129,0.3)] transition-all flex items-center gap-2"
                        >
                          <Activity size={18} /> Resume Execution
                        </button>
                        <button
                          onClick={async () => {
                            await api.retryExecution();
                          }}
                          className="px-5 py-2.5 bg-nude-700 hover:bg-nude-600 text-nude-200 font-semibold text-sm rounded-lg border border-nude-600 transition-all flex items-center gap-2"
                        >
                          Retry Execution
                        </button>
                        <button
                          onClick={async () => {
                            await api.skipExecution();
                          }}
                          className="px-5 py-2.5 bg-nude-700 hover:bg-nude-600 text-nude-200 font-semibold text-sm rounded-lg border border-nude-600 transition-all flex items-center gap-2"
                        >
                          Skip & Continue
                        </button>
                      </div>
                    )}
                    {(status === 'executing' || status === 'fixing') && (
                      <button
                        onClick={async () => {
                          await api.pauseExecution();
                        }}
                        className="px-5 py-2.5 bg-red-500/20 hover:bg-red-500/30 text-red-400 font-semibold text-sm rounded-lg border border-red-500/50 shadow-[0_0_15px_rgba(239,68,68,0.2)] transition-all flex items-center gap-2"
                      >
                        <Square size={18} /> Pause Execution
                      </button>
                    )}
                    {status === 'plan_review' && (
                      <button
                        onClick={async () => {
                          await api.approvePlan();
                          await api.executeAll();
                        }}
                        className="px-5 py-2.5 bg-accent hover:bg-accent/80 text-nude-900 font-semibold text-sm rounded-lg shadow-[0_0_15px_rgba(16,185,129,0.3)] transition-all flex items-center gap-2"
                      >
                        <CheckCircle2 size={18} /> Approve & Execute
                      </button>
                    )}
                    {(status === 'completed' || status === 'idle' || status === 'error') && project?.plan_approved && (
                      <button
                        onClick={async () => {
                          await api.executeAll();
                        }}
                        className="px-5 py-2.5 bg-nude-700 hover:bg-nude-600 text-nude-100 font-semibold text-sm rounded-lg border border-nude-600 shadow-[0_0_15px_rgba(0,0,0,0.2)] transition-all flex items-center gap-2"
                      >
                        <Activity size={18} className="text-accent" /> Check for Errors
                      </button>
                    )}
                  </div>
                </div>

                <div className="flex flex-col gap-4">
                  {project?.epic_queue && project.epic_queue.length > 0 ? (
                    project.epic_queue.map((epic, epicIdx) => {
                      const epicSteps = (project?.plan_steps || []).filter(s => s.epic_id === epic.id);
                      const isExpanded = expandedEpics[epic.id] !== false; // Default to true if undefined
                      
                      let epicStatus = epic.status || 'pending';
                      if (epicSteps.length > 0) {
                        if (epicSteps.some(s => s.status === 'failed')) epicStatus = 'failed';
                        else if (epicSteps.every(s => s.status === 'completed')) epicStatus = 'completed';
                        else if (epicSteps.some(s => s.status === 'in_progress')) epicStatus = 'in_progress';
                        else if (epicSteps.some(s => s.status === 'completed')) epicStatus = 'in_progress';
                        else epicStatus = 'pending';
                      }

                      return (
                        <div key={epic.id} className={`rounded-xl border ${epicStatus === 'in_progress' ? 'border-accent/50 bg-accent/5' : epicStatus === 'completed' ? 'border-nude-700/50 bg-nude-850/50' : 'border-nude-800 bg-nude-900'} overflow-hidden transition-all shadow-lg`}>
                          {/* Epic Header */}
                          <div 
                            className="p-4 flex items-center justify-between cursor-pointer hover:bg-nude-800/50 transition-colors select-none"
                            onClick={() => toggleEpic(epic.id)}
                          >
                            <div className="flex items-center gap-3">
                              <button className="text-nude-500 hover:text-nude-300 transition-colors">
                                {isExpanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                              </button>
                              <span className={`flex items-center justify-center w-8 h-8 rounded-lg text-xs font-bold ${epicStatus === 'completed' ? 'bg-emerald-500/20 text-emerald-400' : epicStatus === 'in_progress' ? 'bg-accent text-nude-900' : 'bg-nude-800 text-nude-500 border border-nude-700'}`}>
                                E{epicIdx + 1}
                              </span>
                              <div>
                                <h3 className={`font-mono text-base ${epicStatus === 'in_progress' ? 'text-accent' : 'text-nude-200'}`}>{epic.name}</h3>
                                <div className="text-xs text-nude-500 font-sans mt-0.5">{epic.purpose}</div>
                              </div>
                            </div>
                            <div className="flex items-center gap-4">
                              {epicSteps.length > 0 && (
                                <div className="flex items-center gap-2">
                                  {/* Completion Circle */}
                                  <div className="relative flex items-center justify-center w-8 h-8" title={`${Math.round((epicSteps.filter(s => s.status === 'completed').length / epicSteps.length) * 100)}% completed`}>
                                    <svg className="w-8 h-8 transform -rotate-90">
                                      <circle
                                        className="text-nude-800"
                                        strokeWidth="2.5"
                                        stroke="currentColor"
                                        fill="transparent"
                                        r="12"
                                        cx="16"
                                        cy="16"
                                      />
                                      <circle
                                        className={`${epicStatus === 'completed' ? 'text-emerald-500' : 'text-accent'} transition-all duration-500 ease-in-out`}
                                        strokeWidth="2.5"
                                        strokeDasharray={2 * Math.PI * 12}
                                        strokeDashoffset={(2 * Math.PI * 12) - ((Math.round((epicSteps.filter(s => s.status === 'completed').length / epicSteps.length) * 100) / 100) * (2 * Math.PI * 12))}
                                        strokeLinecap="round"
                                        stroke="currentColor"
                                        fill="transparent"
                                        r="12"
                                        cx="16"
                                        cy="16"
                                      />
                                    </svg>
                                    <span className="absolute text-[8px] font-mono text-nude-400">
                                      {Math.round((epicSteps.filter(s => s.status === 'completed').length / epicSteps.length) * 100)}%
                                    </span>
                                  </div>
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      api.retryExecution(epicSteps[0].step_number);
                                    }}
                                    className="p-1.5 text-nude-500 hover:text-accent hover:bg-nude-800 rounded transition-colors"
                                    title="Retry this entire Epic"
                                  >
                                    <RotateCcw size={16} />
                                  </button>
                                </div>
                              )}
                              <span className="text-xs uppercase tracking-widest font-mono text-nude-500 bg-nude-900 px-2 py-1 rounded border border-nude-800/50 shadow-inner-soft">
                                {epicStatus.replace('_', ' ')}
                              </span>
                            </div>
                          </div>
                          
                          {/* Epic Steps */}
                          {isExpanded && (
                            <div className="border-t border-nude-800/50 bg-nude-900/30 p-4 pl-12 flex flex-col gap-3">
                              {epicSteps.length === 0 ? (
                                <div className="text-xs text-nude-500 font-mono italic">Waiting for JIT Planning...</div>
                              ) : (
                                epicSteps.map((step) => (
                                  <div key={step.step_number} className={`p-4 rounded-lg border ${step.status === 'in_progress' ? 'border-accent/40 bg-accent/5' : step.status === 'completed' ? 'border-nude-700/50 bg-nude-850/50' : 'border-nude-800/50 bg-nude-900/50'} transition-all flex flex-col gap-2`}>
                                    <div className="flex items-center justify-between">
                                      <div className="flex items-center gap-3">
                                        <span className={`text-xs font-mono w-6 text-center ${step.status === 'in_progress' ? 'text-accent animate-pulse' : 'text-nude-500'}`}>
                                          {step.step_number}
                                        </span>
                                        <h4 className={`font-mono text-sm ${step.status === 'in_progress' ? 'text-accent' : 'text-nude-300'}`}>{step.title || step.file_path}</h4>
                                      </div>
                                      <div className="flex items-center gap-3">
                                        {step.status === 'completed' && (
                                          <button
                                            onClick={() => api.retryExecution(step.step_number)}
                                            className="p-1 text-nude-500 hover:text-accent hover:bg-nude-800 rounded transition-colors"
                                            title="Retry this step and all steps after it"
                                          >
                                            <RotateCcw size={14} />
                                          </button>
                                        )}
                                        <span className="text-[10px] uppercase tracking-widest font-mono text-nude-500">
                                          {step.status}
                                        </span>
                                      </div>
                                    </div>
                                    <p className="text-xs text-nude-400 font-sans ml-9">
                                      {step.description}
                                    </p>
                                  </div>
                                ))
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })
                  ) : (project?.plan_steps && project.plan_steps.length > 0) ? (
                    // Fallback for simple projects without epics
                    project.plan_steps.map((step, idx) => (
                      <div key={idx} className={`p-5 rounded-xl border ${step.status === 'in_progress' ? 'border-accent/50 bg-accent/5 shadow-[0_0_15px_rgba(16,185,129,0.1)]' : step.status === 'completed' ? 'border-nude-700/50 bg-nude-850/50' : 'border-nude-800 bg-nude-900'} transition-all`}>
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-3">
                            <span className={`flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold ${step.status === 'completed' ? 'bg-emerald-500/20 text-emerald-400' : step.status === 'in_progress' ? 'bg-accent text-nude-900 animate-pulse' : 'bg-nude-800 text-nude-500'}`}>
                              {idx + 1}
                            </span>
                            <h3 className={`font-mono text-base ${step.status === 'in_progress' ? 'text-accent' : 'text-nude-200'}`}>{step.title || step.file_path}</h3>
                          </div>
                          <div className="flex items-center gap-3">
                            {step.status === 'completed' && (
                              <button
                                onClick={() => api.retryExecution(step.step_number)}
                                className="p-1 text-nude-500 hover:text-accent hover:bg-nude-800 rounded transition-colors"
                                title="Retry this step and all steps after it"
                              >
                                <RotateCcw size={14} />
                              </button>
                            )}
                            <span className="text-xs uppercase tracking-widest font-mono text-nude-500">
                              {step.status}
                            </span>
                          </div>
                        </div>
                        <p className="text-sm text-nude-400 font-sans ml-10">
                          {step.description}
                        </p>
                      </div>
                    ))
                  ) : (
                    <div className="text-center p-12 text-nude-500 font-mono text-sm border border-dashed border-nude-800 rounded-xl">
                      No plan generated yet.
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Code Tab */}
            <div className={`absolute inset-0 transition-opacity duration-200 ${activeTab === 'code' ? 'opacity-100 z-10' : 'opacity-0 z-0 pointer-events-none'}`}>
              {selectedFile ? (
                <CodeViewer filePath={selectedFile} content={fileContent} />
              ) : (
                <div className="h-full w-full flex items-center justify-center flex-col gap-4 text-nude-600 font-mono text-sm opacity-50">
                   <Code2 size={48} strokeWidth={1} />
                   <p>No file selected</p>
                </div>
              )}
            </div>
            
            {/* Knowledge Tab */}
            <div className={`absolute inset-0 bg-nude-850/30 transition-opacity duration-200 p-8 ${activeTab === 'graph' ? 'opacity-100 z-10 overflow-y-auto custom-scrollbar' : 'opacity-0 z-0 pointer-events-none'}`}>
              <div className="max-w-3xl mx-auto">
                <h2 className="text-2xl font-semibold text-nude-200 mb-6 flex items-center gap-3">
                  <BookOpen className="text-accent" /> Context Engine Knowledge
                </h2>
                {/* KNOWLEDGE TAB */}
                {activeTab === 'graph' && (
                  <div className="h-[650px] w-full bg-nude-850 border border-nude-800 rounded-lg flex flex-col overflow-hidden relative shadow-lg">
                    <ArchitectureGraph astNodeCount={workspaceFiles.length * 12} />
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Bottom Terminal */}
          <section className={`border-t border-nude-700 bg-nude-850 flex flex-col transition-all duration-300 shrink-0 ${isTerminalOpen ? 'h-48' : 'h-10'}`}>
            <div className="h-10 shrink-0 flex items-center justify-between px-4 border-b border-nude-700/50 cursor-pointer hover:bg-nude-850/50 transition-colors" onClick={() => setIsTerminalOpen(!isTerminalOpen)}>
              <div className="flex items-center gap-2 text-xs font-mono uppercase tracking-widest text-nude-400">
                <Terminal size={14} /> Terminal Output
              </div>
            </div>
            <div className="flex-1 p-3 font-mono text-xs overflow-y-auto custom-scrollbar" ref={terminalRef}>
              {processOutput.map((out, idx) => (
                <div key={idx} className={`whitespace-pre-wrap leading-relaxed ${out.type === 'stderr' ? 'text-red-400/80' : 'text-nude-400'}`}>
                  {out.text}
                </div>
              ))}
              {processRunning && (
                <div className="mt-2 flex gap-2">
                  <span className="text-accent">➜</span>
                  <span className="bg-nude-400 w-2 h-4 animate-pulse"></span>
                </div>
              )}
              {!processRunning && processOutput.length === 0 && (
                <div className="text-nude-600 italic">No output yet...</div>
              )}
            </div>
          </section>
        </main>

        {/* Right Sidebar: AI Chatbot */}
        <aside className="w-[420px] border-l border-nude-700 bg-nude-850 flex flex-col shrink-0">
          <div className="p-4 border-b border-nude-700/50 flex items-center gap-3 shrink-0">
            <div className="w-8 h-8 rounded-lg bg-nude-800 border border-nude-700 flex items-center justify-center text-accent">
              <Sparkles size={16} />
            </div>
            <div>
              <h3 className="text-sm font-medium text-nude-200">AI Assistant</h3>
              <div className="text-[10px] font-mono text-nude-500 uppercase tracking-wider">{status || 'Ready'}</div>
            </div>
          </div>
          
          <div className="flex-1 overflow-y-auto custom-scrollbar p-4" ref={chatRef}>
            <div className="text-center text-[10px] text-nude-600 font-mono uppercase tracking-widest my-2">Session Initialized</div>
            
            {messages.length === 0 && (
              <div className="flex gap-3 my-4">
                <div className="w-6 h-6 rounded bg-nude-800 border border-nude-700 flex-shrink-0 flex items-center justify-center text-accent mt-1">
                  <Sparkles size={12} />
                </div>
                <div className="flex-1 text-sm text-nude-300 font-sans pt-1">
                  Hello. I am ready to write and edit code for your project. What would you like to build?
                </div>
              </div>
            )}

            {/* Render Chat History */}
            {messages.map((msg, idx) => renderMessage(msg, idx))}

            {/* Render Current Streaming Message */}
            {(thinkingText || isThinking || llmText || llmStreaming) && (
              <div className="flex flex-col gap-2 my-4">
                {(thinkingText || isThinking) && (
                  <details className="group border border-nude-800 bg-nude-900/50 rounded-lg overflow-hidden ml-9" open>
                    <summary className="text-xs text-nude-500 font-mono p-2 cursor-pointer hover:bg-nude-800 transition-colors select-none list-none flex items-center gap-2">
                      <span className="group-open:rotate-90 transition-transform text-nude-600">▶</span>
                      Thinking Process
                    </summary>
                    <div ref={currentThinkingRef} className="p-3 text-xs text-nude-500 font-mono whitespace-pre-wrap border-t border-nude-800 max-h-[250px] overflow-y-auto custom-scrollbar">
                      {thinkingText}
                      {isThinking && <span className="inline-block w-1.5 h-3 ml-1 bg-nude-600 animate-pulse align-middle"></span>}
                    </div>
                  </details>
                )}

                {(llmText || llmStreaming) && (
                  <div className="flex gap-3">
                    <div className="w-6 h-6 rounded bg-nude-800 border border-nude-700 flex-shrink-0 flex items-center justify-center text-accent mt-1">
                      <Sparkles size={12} />
                    </div>
                    <div ref={currentLlmRef} className="flex-1 text-xs text-nude-200 font-mono pt-1 whitespace-pre-wrap max-h-[350px] overflow-y-auto custom-scrollbar bg-nude-900/50 p-3 rounded-lg border border-nude-800/80 shadow-inner-soft">
                      {formatAgentMessage(llmText)}
                      {llmStreaming && <span className="inline-block w-1.5 h-4 ml-1 bg-accent animate-pulse align-middle"></span>}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="p-4 bg-nude-850 shrink-0">
            {attachedFiles.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-2">
                {attachedFiles.map((file, idx) => (
                  <div key={idx} className="flex items-center gap-2 bg-nude-800 border border-nude-700 rounded-full px-3 py-1 text-xs text-nude-200">
                    <Paperclip size={12} className="text-accent" />
                    <span className="truncate max-w-[150px]">{file.name}</span>
                    <button type="button" onClick={() => setAttachedFiles(prev => prev.filter((_, i) => i !== idx))} className="hover:text-red-400 transition-colors">
                      <X size={12} />
                    </button>
                  </div>
                ))}
              </div>
            )}
            <form onSubmit={handleSendPrompt} className="relative flex items-end bg-nude-900 border border-nude-700 rounded-xl focus-within:border-accent focus-within:ring-1 focus-within:ring-accent transition-all p-1">
              <input
                type="file"
                multiple
                id="chat-file-upload"
                className="hidden"
                onChange={(e) => {
                  if (e.target.files) {
                    setAttachedFiles(prev => [...prev, ...Array.from(e.target.files)]);
                  }
                }}
              />
              <label 
                htmlFor="chat-file-upload" 
                className="w-8 h-8 m-1 flex-shrink-0 flex items-center justify-center text-nude-500 hover:text-accent cursor-pointer transition-colors"
                title="Attach Documents"
              >
                <Paperclip size={16} />
              </label>
              <textarea 
                className="w-full bg-transparent border-none px-2 py-2.5 text-sm text-nude-200 focus:outline-none placeholder:text-nude-600 resize-none max-h-32 custom-scrollbar min-h-[40px]"
                placeholder="Ask the agent to code, or attach docs..."
                value={prompt}
                onChange={e => setPrompt(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSendPrompt(e);
                  }
                }}
                rows={1}
              />
              <button 
                type="submit"
                disabled={!prompt.trim() && attachedFiles.length === 0}
                className="w-8 h-8 m-1 flex-shrink-0 flex items-center justify-center bg-nude-800 text-nude-400 rounded-lg hover:bg-nude-700 hover:text-accent disabled:opacity-50 transition-colors"
              >
                <Send size={14} />
              </button>
            </form>
          </div>
        </aside>
      </div>
    </div>
  );
}
