import { FileCode } from 'lucide-react';

export default function CodeViewer({ filePath, content }) {
  if (!filePath) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-nude-600 font-mono text-sm opacity-50">
        <FileCode size={48} strokeWidth={1} className="mb-4" />
        <p>No file selected</p>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-transparent">
      {/* Header */}
      <div className="h-10 shrink-0 flex items-center px-4 bg-nude-850 border-b border-nude-700/50">
        <span className="text-xs font-mono text-nude-300">{filePath}</span>
      </div>
      
      {/* Code Area */}
      <div className="flex-1 overflow-auto custom-scrollbar p-4 bg-nude-900/50">
        <div className="flex">
          {/* Line Numbers */}
          <div className="flex flex-col text-right pr-4 select-none border-r border-nude-700/50 mr-4 text-nude-600 font-mono text-xs leading-relaxed shrink-0 min-w-[2rem]">
            {content.split('\n').map((_, i) => (
              <span key={i}>{i + 1}</span>
            ))}
          </div>
          
          {/* Content */}
          <pre className="font-mono text-xs leading-relaxed text-nude-200 whitespace-pre overflow-visible">
            {content || ' '}
          </pre>
        </div>
      </div>
    </div>
  );
}
