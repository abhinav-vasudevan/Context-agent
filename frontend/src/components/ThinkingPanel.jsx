import { useRef, useEffect } from 'react';
import './ThinkingPanel.css';

export default function ThinkingPanel({ text, isThinking }) {
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [text]);

  return (
    <div className="thinking-panel">
      <div className="thinking-panel-header">
        <span className="thinking-label">
          {isThinking ? (
            <>
              <span className="thinking-dot" />
              Model Reasoning
            </>
          ) : text ? (
            '🧠 Reasoning Complete'
          ) : (
            '🧠 Model Reasoning'
          )}
        </span>
      </div>
      <div className="thinking-panel-body" ref={scrollRef}>
        {text || isThinking ? (
          <pre className="thinking-text">
            {text}
            {isThinking && <span className="thinking-cursor">▊</span>}
          </pre>
        ) : (
          <div className="thinking-empty">
            <span className="thinking-icon">🧠</span>
            <p>The model's internal chain-of-thought reasoning will appear here.</p>
          </div>
        )}
      </div>
    </div>
  );
}
