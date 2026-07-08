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
            {/* Chat Input */}
            <form onSubmit={handleSendPrompt} className="p-4 bg-nude-900 border-t border-nude-800">
              {attachedFiles.length > 0 && (
                <div className="flex flex-wrap gap-2 mb-3">
                  {attachedFiles.map((file, idx) => (
                    <div key={idx} className="flex items-center gap-2 bg-nude-800 border border-nude-700 rounded-full px-3 py-1 text-xs text-nude-200">
                      <Paperclip size={12} className="text-accent" />
                      <span className="truncate max-w-[150px]">{file.name}</span>
                      <button type="button" onClick={() => setAttachedFiles(prev => prev.filter((_, i) => i !== idx))} className="hover:text-red-400">
                        <X size={12} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <div className="relative flex items-center bg-nude-950 border border-nude-800 rounded-lg overflow-hidden focus-within:border-nude-600 focus-within:ring-1 focus-within:ring-nude-600 transition-all">
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
                  className="p-3 text-nude-500 hover:text-accent cursor-pointer transition-colors"
                  title="Attach Documents"
                >
                  <Paperclip size={18} />
                </label>
                <input
                  type="text"
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder="Tell Context Engine what to build, or ask about attached docs..."
                  className="w-full bg-transparent text-nude-200 placeholder-nude-600 py-4 px-2 focus:outline-none"
                />
                <button
                  type="submit"
                  disabled={!prompt.trim() && attachedFiles.length === 0}
"""

content = re.sub(r'\{\/\* Chat Input \*\/\}\s*<form onSubmit=\{handlePromptSubmit\} className="p-4 bg-nude-900 border-t border-nude-800">\s*<div className="relative flex items-center">\s*<input\s*type="text"\s*value=\{prompt\}\s*onChange=\{\(e\) => setPrompt\(e\.target\.value\)\}\s*placeholder="Tell Context Engine what to build\.\.\."\s*className="w-full bg-nude-950 text-nude-200 placeholder-nude-600 rounded-lg py-4 pl-4 pr-12 focus:outline-none focus:ring-1 focus:ring-nude-700 border border-nude-800"\s*\/>\s*<button\s*type="submit"\s*disabled=\{!prompt\.trim\(\)\}', ui_code.strip(), content)

with open('frontend/src/pages/Workspace.jsx', 'w') as f:
    f.write(content)

print("Updated Workspace.jsx for attachments")
