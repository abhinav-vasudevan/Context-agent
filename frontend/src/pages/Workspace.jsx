import { useState, useEffect, useRef } from 'react';
import { api } from '../services/api';
import { useWebSocket } from '../hooks/useWebSocket';
import CodeViewer from '../components/CodeViewer';
import { Terminal, FolderTree, Cpu, ArrowLeft, Send, Sparkles, BookOpen, Code2, User, ListTodo, CheckCircle2 } from 'lucide-react';

export default function Workspace({ projectData, onBack }) {
  // ── State ──────────────────────────────────────────────────────────
  const [project, setProject] = useState(projectData);
  const [prompt, setPrompt] = useState(projectData?.original_prompt || '');
  const [status, setStatus] = useState(projectData?.status || 'idle');
  const [statusDetail, setStatusDetail] = useState('');
  
  // Tabs
  const [activeTab, setActiveTab] = useState('code'); // code or knowledge
  const [isTerminalOpen, setIsTerminalOpen] = useState(true);

  // Chat History
  const [messages, setMessages] = useState([]);

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

  // ── WebSocket ──────────────────────────────────────────────────────
  const ws = useWebSocket({
    llm_token: (data) => {
      setLlmStreaming(true);
      setIsThinking(false);
      setLlmText(prev => prev + data.token);
      scrollToBottom(chatRef);
    },
    llm_thinking: (data) => {
      setIsThinking(true);
      setThinkingText(prev => prev + data.token);
      scrollToBottom(chatRef);
    },
    llm_done: () => {
      setLlmStreaming(false);
      setIsThinking(false);
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: llmText,
        thinking: thinkingText
      }]);
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
    error: (data) => {
      setStatusDetail(data.error);
    },
    pong: () => {},
  });

  const scrollToBottom = (ref) => {
    if (ref.current) {
      ref.current.scrollTop = ref.current.scrollHeight;
    }
  };

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
    } catch {}
  }

  useEffect(() => {
    if (project) {
      loadFiles();
      if (project.original_prompt && messages.length === 0) {
        setMessages([{ role: 'user', content: project.original_prompt }]);
      }
    }
  }, [project]);

  useEffect(() => {
    if (status === 'plan_review') {
      setActiveTab('plan');
    }
  }, [status]);

  const handleSendPrompt = (e) => {
    e.preventDefault();
    if (!prompt.trim()) return;
    
    // Add user message to history
    setMessages(prev => [...prev, { role: 'user', content: prompt.trim() }]);
    
    // Clear chat streaming state for new prompt
    setLlmText('');
    setThinkingText('');
    
    api.generatePlan(prompt).catch(console.error);
    setPrompt('');
    setTimeout(() => scrollToBottom(chatRef), 100);
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
              {msg.content}
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
          {status !== 'idle' && (
            <span className="flex items-center gap-2 bg-nude-800 px-2 py-1 rounded-md border border-nude-700">
              <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse"></span>
              {status}
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
          <div className="flex h-10 border-b border-nude-700 bg-nude-850 shrink-0">
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
            <button 
              className={`px-4 flex items-center gap-2 border-r border-nude-700 text-xs font-mono uppercase tracking-widest transition-all ${activeTab === 'graph' ? 'bg-nude-900 text-nude-200 border-t-2 border-t-accent' : 'text-nude-500 hover:bg-nude-800 hover:text-nude-300 border-t-2 border-t-transparent'}`} 
              onClick={() => setActiveTab('graph')}
            >
              <BookOpen size={14} /> Knowledge
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
                </div>

                <div className="flex flex-col gap-4">
                  {(project?.plan_steps || []).map((step, idx) => (
                    <div key={idx} className={`p-5 rounded-xl border ${step.status === 'in_progress' ? 'border-accent/50 bg-accent/5 shadow-[0_0_15px_rgba(16,185,129,0.1)]' : step.status === 'completed' ? 'border-nude-700/50 bg-nude-850/50' : 'border-nude-800 bg-nude-900'} transition-all`}>
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-3">
                          <span className={`flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold ${step.status === 'completed' ? 'bg-emerald-500/20 text-emerald-400' : step.status === 'in_progress' ? 'bg-accent text-nude-900 animate-pulse' : 'bg-nude-800 text-nude-500'}`}>
                            {idx + 1}
                          </span>
                          <h3 className={`font-mono text-base ${step.status === 'in_progress' ? 'text-accent' : 'text-nude-200'}`}>{step.title || step.file_path}</h3>
                        </div>
                        <span className="text-xs uppercase tracking-widest font-mono text-nude-500">
                          {step.status}
                        </span>
                      </div>
                      <p className="text-sm text-nude-400 font-sans ml-10">
                        {step.description}
                      </p>
                    </div>
                  ))}
                  {(!project?.plan_steps || project.plan_steps.length === 0) && (
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
                <div className="p-6 bg-nude-800/50 border border-nude-700 rounded-xl font-mono text-sm leading-relaxed text-nude-300">
                  <p className="mb-4 text-nude-400">The Context Engine automatically ingests your architectural guidelines and project structure into its Neo4j graph and ChromaDB semantic brain.</p>
                  <div className="bg-nude-900 border border-nude-700 p-4 rounded-lg text-nude-400">
                    <pre className="whitespace-pre-wrap font-mono text-xs text-accent">
{`// AST Indexing Status: Online
// Semantic Vector DB: Ready
// Current Indexed Nodes: ${workspaceFiles.length * 12}`}
                    </pre>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Bottom Terminal */}
          <section className={`border-t border-nude-700 bg-[#141210] flex flex-col transition-all duration-300 shrink-0 ${isTerminalOpen ? 'h-48' : 'h-10'}`}>
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
                    <div className="p-3 text-xs text-nude-500 font-mono whitespace-pre-wrap border-t border-nude-800">
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
                    <div className="flex-1 text-xs text-nude-200 font-mono pt-1 whitespace-pre-wrap max-h-[350px] overflow-y-auto custom-scrollbar bg-nude-900/50 p-3 rounded-lg border border-nude-800/80 shadow-inner-soft">
                      {llmText}
                      {llmStreaming && <span className="inline-block w-1.5 h-4 ml-1 bg-accent animate-pulse align-middle"></span>}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="p-4 bg-nude-850 shrink-0">
            <form onSubmit={handleSendPrompt} className="relative flex items-end bg-nude-900 border border-nude-700 rounded-xl focus-within:border-accent focus-within:ring-1 focus-within:ring-accent transition-all p-1">
              <textarea 
                className="w-full bg-transparent border-none px-3 py-2 text-sm text-nude-200 focus:outline-none placeholder:text-nude-600 resize-none max-h-32 custom-scrollbar min-h-[44px]"
                placeholder="Ask the agent to code..."
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
                disabled={!prompt.trim()}
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
