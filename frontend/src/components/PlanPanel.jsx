import { CheckCircle2, Circle, AlertCircle, Loader, FileCode } from 'lucide-react';
import './PlanPanel.css';

export default function PlanPanel({ steps, files, onFileSelect, planText }) {
  function getStepIcon(status) {
    switch (status) {
      case 'completed': return <CheckCircle2 size={18} className="step-icon completed" />;
      case 'in_progress': return <Loader size={18} className="step-icon progress" />;
      case 'failed': return <AlertCircle size={18} className="step-icon failed" />;
      default: return <Circle size={18} className="step-icon pending" />;
    }
  }

  function getStepClass(status) {
    return `plan-step ${status || 'pending'}`;
  }

  return (
    <div className="plan-panel">
      <div className="plan-panel-content">
        {/* Plan Overview */}
        {planText && (
          <div className="plan-overview">
            <pre className="plan-text-content">{planText.split(/## IMPLEMENTATION PLAN|\*\*IMPLEMENTATION PLAN\*\*/i)[0].trim()}</pre>
          </div>
        )}

        {/* Steps */}
        <div className="steps-list">
          <h3 className="panel-title">Implementation Plan</h3>
          {steps.map((step, idx) => (
            <div key={step.step_number} className={getStepClass(step.status)} style={{ animationDelay: `${idx * 0.05}s` }}>
              <div className="step-header">
                {getStepIcon(step.status)}
                <span className="step-number">Step {step.step_number}</span>
                <span className="step-title">{step.title}</span>
              </div>
              <div className="step-details">
                <button
                  className="step-file"
                  onClick={() => onFileSelect(step.file_path)}
                  title={`View ${step.file_path}`}
                >
                  <FileCode size={13} />
                  {step.file_path}
                </button>
                <p className="step-desc">{step.description}</p>
                {step.summary && (
                  <p className="step-summary">✓ {step.summary}</p>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* File Tree */}
        {files.length > 0 && (
          <div className="file-tree">
            <h3 className="panel-title">Workspace Files</h3>
            {files.map(file => (
              <button
                key={file}
                className="file-item"
                onClick={() => onFileSelect(file)}
              >
                <FileCode size={14} />
                <span className="truncate">{file}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
