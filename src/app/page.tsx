import Link from "next/link";

const openingMessage = "Okay Ted, let's do this!";

function getWhatsAppUrl() {
  const number = (process.env.NEXT_PUBLIC_TED_WHATSAPP_NUMBER ?? "").replace(/\D/g, "");
  const base = number ? `https://wa.me/${number}` : "https://wa.me/";
  return `${base}?text=${encodeURIComponent(openingMessage)}`;
}

function WhatsAppLink({ className = "" }: { className?: string }) {
  return (
    <a className={`whatsapp-link ${className}`} href={getWhatsAppUrl()} target="_blank" rel="noreferrer">
      <span className="whatsapp-copy"><strong>Message Ted</strong><small>Free during beta. Opens WhatsApp</small></span>
      <span className="whatsapp-mark" aria-hidden="true">↗</span>
    </a>
  );
}

function TedLogo() {
  return <span className="brand-word" aria-label="Ted">Ted<span className="brand-dot" aria-hidden="true">.</span></span>;
}

export default function Home() {
  return (
    <main>
      <header className="site-header page-shell">
        <a className="brand" href="#top" aria-label="Ted home"><TedLogo /></a>
        <p className="header-note">Your day, remembered.</p>
        <WhatsAppLink className="header-cta" />
      </header>

      <section className="hero page-shell" id="top">
        <div className="hero-copy">
          <p className="eyebrow">Fitness accountability that lives in WhatsApp</p>
          <h1>Your day slipped away. <span>You can still turn it around.</span></h1>
          <p className="hero-lede">Ted remembers your meals, movement, water, and commitments. Then it messages you with the one useful thing you can still do today.</p>
          <p className="hero-flow">Message Ted → tell it what you ate and did → get one nudge and an evening recap.</p>
          <div className="hero-actions"><WhatsAppLink /><p>Nothing to download.<br />It starts in your chat.</p></div>
        </div>

        <div className="rescue-preview" aria-label="Example WhatsApp message from Ted">
          <div className="preview-topline"><span>Example day</span><span className="live-dot">7:42 PM</span></div>
          <div className="chat-window">
            <div className="chat-person"><span>t</span><div><strong>Ted</strong><small>WhatsApp</small></div></div>
            <div className="rescue-message"><p>You’re 2,100 steps short. A 19-minute walk closes the gap.</p><strong>Shoes on?</strong><small>One useful move. No guilt trip.</small></div>
            <div className="user-reply">Going now</div>
            <div className="typing-dots" aria-label="Ted is typing"><i /><i /><i /></div>
          </div>
          <div className="progress-row" aria-label="Example progress"><div><span>Before</span><strong>5,900</strong></div><span className="progress-arrow">→</span><div><span>After the walk</span><strong>8,214 steps</strong></div></div>
        </div>
      </section>

      <section className="review-section page-shell" aria-labelledby="review-title">
        <div className="review-copy"><p className="eyebrow">Example evening review</p><h2 id="review-title">No pretending the day was perfect. Just an honest close.</h2><p>Ted brings the day together so you can see what happened, recover what is still possible, and stop carrying the rest in your head.</p></div>
        <div className="review-card"><span>Evening review</span><h3>Good recovery.</h3><ul><li><b>✓</b> 3 meals logged</li><li><b>✓</b> Water target hit</li><li><b>✓</b> Evening walk done</li><li><b>→</b> Workout moved, not forgotten</li></ul></div>
      </section>

      <section className="privacy-section page-shell" aria-labelledby="privacy-title">
        <p className="privacy-mark" aria-hidden="true">your<br />health.<br />your call.</p>
        <div><p className="eyebrow">Before you start</p><h2 id="privacy-title">Health conversations are personal.</h2><p>Ted stores your profile, messages, plans, logs, and uploaded media so it can remember your day. Ted and the services that run it process this information. To remove it, message “delete my data” in WhatsApp and confirm the request.</p><p>Ted is a habit coach, not medical advice, and should not be used for emergencies, diagnosis, or treatment.</p></div>
      </section>

      <section className="final-cta"><div className="page-shell final-grid"><p className="final-time">Today, whenever you’re ready</p><h2>One message starts the conversation.</h2><WhatsAppLink /></div></section>
      <footer className="site-footer page-shell"><a className="brand" href="#top"><TedLogo /></a><p>Fitness accountability in WhatsApp.</p><Link href="/privacy">Privacy</Link><p>© 2026 Ted</p></footer>
    </main>
  );
}
