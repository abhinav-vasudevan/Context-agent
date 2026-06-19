import { useState, useRef, useEffect } from 'react';
import { Terminal } from 'lucide-react';
import './Modal.css';

export default function InputModal({ prompt, onSubmit, onCancel }) {
  const [value, setValue] = useState('');
  const inputRef = useRef(null);

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.focus();
    }
  }, []);

  function handleSubmit(e) {
    e.preventDefault();
    if (!value.trim()) return;
    onSubmit(value);
  }

  return (
    <div className="modal-overlay">
      <div className="modal-content glass-panel animate-fade-in">
        <div className="modal-header">
          <div className="modal-icon info">
            <Terminal size={24} />
          </div>
          <h2>Input Required</h2>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <p className="modal-question">{prompt || 'The running process is waiting for input:'}</p>
            <input
              ref={inputRef}
              type="text"
              className="input modal-input"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="Type your input here..."
              autoComplete="off"
            />
          </div>
          <div className="modal-actions">
            <button type="button" className="btn btn-secondary" onClick={onCancel}>
              Cancel Process
            </button>
            <button type="submit" className="btn btn-primary" disabled={!value.trim()}>
              Send Input
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
