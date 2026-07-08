import re

with open('frontend/src/pages/Workspace.jsx', 'r') as f:
    content = f.read()

upload_ui = """
                    <div className="bg-nude-850 border border-nude-800 rounded-lg p-6 flex flex-col items-center justify-center gap-4 text-center">
                      <div className="w-12 h-12 rounded-full bg-nude-800 border border-nude-700 flex items-center justify-center text-accent">
                        <BookOpen size={24} />
                      </div>
                      <div>
                        <h3 className="text-lg font-medium text-nude-200">Upload Project Documents</h3>
                        <p className="text-sm text-nude-500 mt-1 max-w-md mx-auto">Upload large specification documents (.txt, .md, .pdf) for the agent to ingest and use as master specifications during planning and coding.</p>
                      </div>
                      <div className="flex items-center gap-3 mt-2">
                        <input 
                          type="file" 
                          id="doc-upload" 
                          className="hidden" 
                          accept=".txt,.md,.pdf"
                          onChange={async (e) => {
                            if (e.target.files && e.target.files.length > 0) {
                              const file = e.target.files[0];
                              const docId = file.name.toLowerCase().replace(/[^a-z0-9]/g, '_');
                              try {
                                setStatus('ingesting_document');
                                setStatusDetail('Chunking and reading doc...');
                                await api.ingestDocument(file, docId);
                                alert("Document ingested successfully!");
                                setStatusDetail('Consolidating docs...');
                                await api.consolidateDocuments();
                                alert("Documents consolidated successfully!");
                                setStatus('idle');
                                setStatusDetail('');
                                
                                // Refresh project state to see the new document
                                const newState = await api.getProjectState();
                                if (newState.project) setProject(newState.project);
                              } catch (err) {
                                alert(`Upload failed: ${err.message}`);
                                setStatus('error');
                                setStatusDetail(err.message);
                              }
                            }
                          }}
                        />
                        <label 
                          htmlFor="doc-upload" 
                          className="px-5 py-2.5 bg-accent hover:bg-accent/80 text-nude-900 font-semibold text-sm rounded-lg shadow-[0_0_15px_rgba(16,185,129,0.3)] transition-all cursor-pointer inline-flex items-center gap-2"
                        >
                          <BookOpen size={18} /> Select Document
                        </label>
                      </div>
                      
                      {project?.user_documents && project.user_documents.length > 0 && (
                        <div className="w-full mt-6 text-left border-t border-nude-700/50 pt-4">
                          <h4 className="text-sm font-medium text-nude-300 mb-3">Ingested Documents:</h4>
                          <div className="flex flex-col gap-2">
                            {project.user_documents.map(doc => (
                              <div key={doc.id} className="bg-nude-900 border border-nude-800 rounded-md p-3 flex justify-between items-center">
                                <div className="flex items-center gap-2">
                                  <BookOpen size={14} className="text-accent" />
                                  <span className="text-xs font-mono text-nude-200">{doc.filename}</span>
                                </div>
                                <span className="text-[10px] text-nude-500 font-mono bg-nude-800 px-2 py-0.5 rounded">
                                  {doc.chunk_count} Chunks
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
"""

# Replace the previous block we inserted
old_ui_start = '<div className="bg-nude-850 border border-nude-800 rounded-lg p-6 flex flex-col items-center justify-center gap-4 text-center">'
old_ui_end = '</div>\n                    \n                    <div className="h-[650px] w-full bg-nude-850 border border-nude-800 rounded-lg flex flex-col overflow-hidden relative shadow-lg">'

# We can just use string replace for this because it's exactly what we added before
pattern = re.compile(r'<div className="bg-nude-850 border border-nude-800 rounded-lg p-6 flex flex-col items-center justify-center gap-4 text-center">.*?</label>\n                      </div>\n                    </div>', re.DOTALL)

new_content = pattern.sub(upload_ui.strip(), content)

with open('frontend/src/pages/Workspace.jsx', 'w') as f:
    f.write(new_content)

print("Updated Workspace.jsx")
