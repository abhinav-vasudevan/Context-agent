import re

with open('frontend/src/pages/Workspace.jsx', 'r') as f:
    content = f.read()

# We need to find the Knowledge tab block and remove it entirely.
# The Knowledge Tab block starts with:
# {/* KNOWLEDGE TAB */}
# {activeTab === 'graph' && (
#   <div className="flex flex-col gap-6">
#     <div className="bg-nude-850 border border-nude-800 rounded-lg p-6 flex flex-col items-center justify-center gap-4 text-center">

# And ends after the ArchitectureGraph div.

replacement = """
                {/* KNOWLEDGE TAB */}
                {activeTab === 'graph' && (
                  <div className="h-[650px] w-full bg-nude-850 border border-nude-800 rounded-lg flex flex-col overflow-hidden relative shadow-lg">
                    <ArchitectureGraph astNodeCount={workspaceFiles.length * 12} />
                  </div>
                )}
"""

pattern = re.compile(r'\{\s*/\*\s*KNOWLEDGE TAB\s*\*/\s*\}.*?ArchitectureGraph astNodeCount=\{workspaceFiles\.length \* 12\} />\s*</div>\s*</div>\s*\)\}', re.DOTALL)

new_content = pattern.sub(replacement.strip(), content)

with open('frontend/src/pages/Workspace.jsx', 'w') as f:
    f.write(new_content)

print("Knowledge tab cleaned up")
