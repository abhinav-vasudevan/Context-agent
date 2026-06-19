import { Shield, Check, X } from 'lucide-react';
import './Modal.css';

export default function PermissionModal({ question, defaultValue, onResponse }) {
  return (
    <div className="modal-overlay permission-overlay">
      <div className="modal-content glass-panel animate-fade-in">
        <div className="modal-header">
          <div className="modal-icon warning">
            <Shield size={24} />
          </div>
          <h2>Permission Required</h2>
        </div>
        <div className="modal-body">
          <p className="modal-question">{question}</p>
          <p className="modal-warning">
            The agent is requesting to execute code on your machine.
            Ensure you trust the generated code before approving.
          </p>
        </div>
        <div className="modal-actions">
          <button
            className="btn btn-secondary"
            onClick={() => onResponse(false)}
            autoFocus={!defaultValue}
          >
            <X size={16} /> Skip Execution
          </button>
          <button
            className="btn btn-primary"
            onClick={() => onResponse(true)}
            autoFocus={defaultValue}
          >
            <Check size={16} /> Allow Execution
          </button>
        </div>
      </div>
    </div>
  );
}
