export default function Hero() {
  return (
    <section className="hero" id="top">
      <div className="hero-grid" aria-hidden />
      <div className="hero-content">
        <p className="eyebrow">Location-aware efficiency</p>
        <h1>
          Find efficiency optimisations for your data center <span className="accent">— based on where it is.</span>
        </h1>
        <p className="lead">
          Climate, grid mix, water and waste-heat demand differ from place to place. Heat Beat maps data
          centers worldwide and shows which cooling, energy and heat-reuse strategies make sense at each site.
        </p>
        <div className="hero-actions">
          <a href="#map" className="btn btn-primary">Explore the map</a>
          <a href="#how" className="btn btn-ghost">How it works</a>
        </div>
        <ul className="features" id="how">
          <li><strong>01</strong><span>Search or pick a data center on the map</span></li>
          <li><strong>02</strong><span>We analyse local climate & energy conditions</span></li>
          <li><strong>03</strong><span>Get concrete optimisation recommendations</span></li>
        </ul>
      </div>
      <a href="#map" className="scroll-hint" aria-label="Scroll to map">
        <span />
      </a>
    </section>
  );
}
