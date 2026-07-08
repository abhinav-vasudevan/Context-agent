import re

with open('frontend/src/pages/Workspace.jsx', 'r') as f:
    content = f.read()

upload_ui = """
                      {project?.global_master_summary && (
                        <div className="w-full mt-6 text-left border-t border-nude-700/50 pt-4 mb-4">
                          <h4 className="text-sm font-medium text-accent mb-2">Global Master Specification:</h4>
                          <div className="p-4 bg-nude-900/50 border border-accent/20 rounded-md text-xs text-nude-300 font-sans whitespace-pre-wrap leading-relaxed shadow-inner-soft">
                            {project.global_master_summary}
                          </div>
                        </div>
                      )}

                      {project?.user_documents && project.user_documents.length > 0 && (
                        <div className="w-full mt-2 text-left border-t border-nude-700/50 pt-4">
                          <h4 className="text-sm font-medium text-nude-300 mb-3">Individual Ingested Documents:</h4>
"""

# Replace the beginning of the Ingested Documents & Summaries block
pattern = re.compile(r'\{\s*project\?\.\s*user_documents\s*&&\s*project\.user_documents\.length\s*>\s*0\s*&&\s*\(\s*<div\s+className="w-full\s+mt-6\s+text-left\s+border-t\s+border-nude-700/50\s+pt-4">\s*<h4\s+className="text-sm\s+font-medium\s+text-nude-300\s+mb-3">Ingested Documents & Summaries:</h4>')

new_content = pattern.sub(upload_ui.strip(), content)

with open('frontend/src/pages/Workspace.jsx', 'w') as f:
    f.write(new_content)

print("Updated Workspace.jsx")
