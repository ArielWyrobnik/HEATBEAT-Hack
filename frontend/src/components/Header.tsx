import { useEffect, useState } from 'react';
import { api } from '../api';

export default function Header() {
  // Feedback link is set on the host (FEEDBACK_URL), so it can change without a new build.
  const [feedback, setFeedback] = useState<string | null>(null);
  useEffect(() => { api.config().then((c) => setFeedback(c.feedback_url)).catch(() => undefined); }, []);

  return (
    <header className="header">
      <a href="#top" className="brand">
        <svg viewBox="0 0 32 32" width="28" height="28" aria-hidden>
          <path d="M3 17h6l3-7 4 13 3-6h10" fill="none" stroke="currentColor" strokeWidth="2.6"
            strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Heat Beat
      </a>
      <div className="header-right">
        {feedback && (
          <a className="feedback-link" href={feedback} target="_blank" rel="noreferrer">Give feedback</a>
        )}
        <div className="event">
          <span className="event-dot" /> NVIDIA Hackathon
        </div>
      </div>
    </header>
  );
}
