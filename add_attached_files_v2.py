import re

with open('frontend/src/pages/Workspace.jsx', 'r') as f:
    content = f.read()

# Add Lucide icon Paperclip, X
content = content.replace("Send, Sparkles, BookOpen", "Send, Sparkles, BookOpen, Paperclip, X")

# Add state
state_code = """
  // Chat History
  const [messages, setMessages] = useState([]);
  const [attachedFiles, setAttachedFiles] = useState([]);
"""
content = re.sub(r'// Chat History\s*const \[messages, setMessages\] = useState\(\[\]\);', state_code.strip(), content)

# Modify handleSendPrompt
send_prompt = """
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
      api.projectFollowup(prompt.trim() || 'Please process the attached documents.', attachedFiles).catch(console.error);
    } else {
      api.generatePlan(prompt.trim(), attachedFiles).then((res) => {
        if (res.success) {
          if (res.project) {
            setProject(res.project);
          } else if (res.plan_steps) {
            setProject(prev => ({ ...prev, plan_steps: res.plan_steps }));
          }
        }
      }).catch(console.error);
    }

    setPrompt('');
    setAttachedFiles([]);
    setTimeout(() => scrollToBottom(chatRef, true), 100);
  };
"""

content = re.sub(r'const handleSendPrompt = \(e\) => \{[\s\S]*?setTimeout\(\(\) => scrollToBottom\(chatRef, true\), 100\);\s*\};', send_prompt.strip(), content)

# Modify Chat Input UI
ui_code = """
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
"""

content = re.sub(r'<div className="p-4 bg-nude-850 shrink-0">\s*<form onSubmit=\{handleSendPrompt\} className="relative flex items-end bg-nude-900 border border-nude-700 rounded-xl focus-within:border-accent focus-within:ring-1 focus-within:ring-accent transition-all p-1">\s*<textarea[\s\S]*?className="w-8 h-8 m-1 flex-shrink-0 flex items-center justify-center bg-nude-800 text-nude-400 rounded-lg hover:bg-nude-700 hover:text-accent disabled:opacity-50 transition-colors"\s*>\s*<Send size=\{14\} \/>\s*<\/button>\s*<\/form>\s*<\/div>', ui_code.strip(), content)

with open('frontend/src/pages/Workspace.jsx', 'w') as f:
    f.write(content)

print("Updated Workspace.jsx for attachments v2")
