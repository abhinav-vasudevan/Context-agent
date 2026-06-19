import { useRef, useEffect, useState } from 'react';
import { Send, Square } from 'lucide-react';
import './OutputPanel.css';

export default function OutputPanel({ output, running, onSendInput, onKill, onClear }) {
  const scrollRef = useRef(null);
  const [inputValue, setInputValue] = useState('');
  const inputRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [output]);

  function handleSubmit(e) {
    e.preventDefault();
    if (!inputValue.trim()) return;
    onSendInput(inputValue);
    setInputValue('');
  }

  // Focus input when process starts running
  useEffect(() => {
    if (running && inputRef.current) {
      inputRef.current.focus();
    }
  }, [running]);

  return (
    <div className="output-panel">
      {/* Terminal Output */}
      <div className="output-display" ref={scrollRef}>
        <div className="output-header-controls" style={{position: 'absolute', right: '10px', top: '10px', zIndex: 10}}>
           {output.length > 0 && <button className="btn btn-secondary btn-sm" onClick={onClear}>Clear Output</button>}
        </div>
        {output.length === 0 ? (
          <div className="output-empty">
            <p>Process output will appear here when code is executed.</p>
          </div>
        ) : (
          <div className="output-lines">
            {output.map((entry, idx) => (
              <span
                key={idx}
                className={`output-line ${entry.type}`}
              >
                {entry.text}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Input Area — Clean, prominent design */}
      <div className="output-input-area">
        <form className="output-input-form" onSubmit={handleSubmit}>
          <div className="input-wrapper">
            <span className="input-prompt-label">
              {running ? '›' : '#'}
            </span>
            <input
              ref={inputRef}
              type="text"
              className="output-input"
              placeholder={running ? "Type your input here and press Enter..." : "Process not running"}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              disabled={!running}
              id="process-input"
              autoComplete="off"
            />
            <button
              type="submit"
              className="btn btn-primary btn-sm send-btn"
              disabled={!running || !inputValue.trim()}
              id="send-input-btn"
            >
              <Send size={14} />
              Send
            </button>
          </div>
          {running && (
            <button
              type="button"
              className="btn btn-danger btn-sm"
              onClick={onKill}
              id="kill-btn"
            >
              <Square size={12} />
              Stop
            </button>
          )}
        </form>
        {running && (
          <p className="input-hint">
            The program is running. If it's waiting for input, type your response above and press Enter.
          </p>
        )}
      </div>
    </div>
  );
}
