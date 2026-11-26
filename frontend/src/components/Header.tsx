export default function Header() {
  return (
    <header className="header">
      <a href="#top" className="brand">
        <svg viewBox="0 0 32 32" width="28" height="28" aria-hidden>
          <path d="M3 17h6l3-7 4 13 3-6h10" fill="none" stroke="currentColor" strokeWidth="2.6"
            strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Heat Beat
      </a>
      <div className="event">
        <span className="event-dot" /> NVIDIA Hackathon
      </div>
    </header>
  );
}
