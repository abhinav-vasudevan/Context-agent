import { FileCode } from 'lucide-react';
import './CodeViewer.css';

export default function CodeViewer({ filePath, content, files, onFileSelect }) {
  return (
    <div className="code-viewer">
      <div className="code-sidebar">
        <div className="sidebar-title">Files</div>
        {files.map(file => (
          <button
            key={file}
            className={`sidebar-file ${file === filePath ? 'active' : ''}`}
            onClick={() => onFileSelect(file)}
          >
            <FileCode size={13} />
            <span className="truncate">{file}</span>
          </button>
        ))}
        {files.length === 0 && (
          <div className="sidebar-empty">No files yet</div>
        )}
      </div>
      <div className="code-main">
        {filePath ? (
          <>
            <div className="code-header">
              <span className="code-filename">{filePath}</span>
            </div>
            <div className="code-body">
              <pre className="code-content">
                {content.split('\n').map((line, i) => (
                  <div key={i} className="code-line">
                    <span className="line-number">{i + 1}</span>
                    <span className="line-content">{line || ' '}</span>
                  </div>
                ))}
              </pre>
            </div>
          </>
        ) : (
          <div className="code-empty">
            <FileCode size={40} />
            <p>Select a file to view its contents</p>
          </div>
        )}
      </div>
    </div>
  );
}
