import { useRef, useEffect } from 'react';
import './LLMStream.css';

export default function LLMStream({ text, streaming }) {
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [text]);

  return (
    <div className="llm-stream">
      <div className="llm-stream-header">
        <span className="llm-label">
          {streaming ? (
            <>
              <span className="typing-dot" />
              AI is thinking...
            </>
          ) : text ? (
            'AI Output'
          ) : (
            'Waiting for AI...'
          )}
        </span>
      </div>
      <div className="llm-stream-body" ref={scrollRef}>
        {text ? (
          <pre className="llm-text">{text}{streaming && <span className="cursor-blink">▊</span>}</pre>
        ) : (
          <div className="llm-empty">
            <p>AI output will appear here as code is being generated.</p>
          </div>
        )}
      </div>
    </div>
  );
}
