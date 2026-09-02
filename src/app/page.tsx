import Image from "next/image";
import Link from "next/link";
import tedMascot from "../../design-experiments/ted-landing-tbh/art/ted.png";

const openingMessage = "Okay Ted, let's do this 🫡";

function getWhatsAppUrl() {
  const number = (process.env.NEXT_PUBLIC_TED_WHATSAPP_NUMBER ?? "").replace(/\D/g, "");
  return `${number ? `https://wa.me/${number}` : "https://wa.me/"}?text=${encodeURIComponent(openingMessage)}`;
}

function WhatsAppLink({ label = "Start on WhatsApp", dark = false }: { label?: string; dark?: boolean }) {
  return <a className={`wa-button${dark ? " wa-button-dark" : ""}`} href={getWhatsAppUrl()} target="_blank" rel="noreferrer"><span aria-hidden="true">◔</span><strong>{label}</strong><b aria-hidden="true">↗</b></a>;
}

function Logo() {
  return <span className="ted-logo" aria-label="Ted">t<span>e</span>d<i>.</i></span>;
}

function SmallAvatar() {
  return <span className="small-avatar" aria-hidden="true">t.</span>;
}

export default function Home() {
  return (
    <main id="top">
      <header className="reference-header page-shell">
        <a href="#top" aria-label="Ted home"><Logo /></a>
        <nav aria-label="Main navigation"><a href="#what">What Ted does</a><a href="#day">A day with Ted</a><a href="#privacy">Privacy</a></nav>
        <WhatsAppLink label="Message Ted" dark />
      </header>

      <section className="reference-hero page-shell">
        <div className="hero-words">
          <p className="kicker">fitness follow-through, minus the guilt trip</p>
          <h1><span>your health day,</span><em>remembered.</em></h1>
          <p className="hero-copy">Ted lives in WhatsApp, keeps track of what you ate and did, and gives you the one useful nudge that still fits today.</p>
          <div className="hero-action"><WhatsAppLink /><small>18+ beta · no app · no login</small></div>
        </div>

        <div className="mascot-stage" aria-label="Ted, the WhatsApp fitness coach">
          <div className="orange-shape"><Image src={tedMascot} alt="Ted, a friendly illustrated coach" width={1024} height={1024} priority sizes="(max-width: 800px) 90vw, 48vw" /></div>
          <span className="float-tag tag-top">friend first</span><span className="float-tag tag-side">coach second</span>
          <div className="scribble-arrow" aria-hidden="true">↝</div>
          <div className="quick-chat"><SmallAvatar /><p>arre, you’re 2,100 steps short. 19 minutes closes it.</p></div>
        </div>
      </section>

      <section className="marquee" aria-label="Ted's promise"><div><span>one chat</span><i>✦</i><span>your whole day</span><i>✦</i><span>one useful nudge</span><i>✦</i><span>no shame</span></div></section>

      <section className="intro-section page-shell" id="what" aria-labelledby="intro-title">
        <p className="section-label">To be honest</p>
        <div className="intro-copy"><h2 id="intro-title">Tracking isn’t the hard part.<br /><em>Remembering to act is.</em></h2><p>Your meals are in one app. Water is another alarm. Steps sit somewhere else. Ted keeps the thread in the chat you already open all day.</p></div>
      </section>

      <section className="story-section">
        <div className="page-shell story-shell">
          <div className="story-title"><p className="section-label light">A day with Ted</p><h2>The day gets busy.<br /><em>Ted doesn’t lose the plot.</em></h2></div>
          <div className="story-chat" id="day">
            <div className="chat-header"><SmallAvatar /><div><strong>Ted</strong><small>online</small></div><span>•••</span></div>
            <div className="chat-body">
              <time>1:14 PM</time>
              <p className="chat-bubble user">2 rotis and paneer for lunch</p>
              <p className="chat-bubble ted">paneer doing the heavy lifting, nice. roughly 520 kcal · 25g protein · 58g carbs · 22g fat · 8g fiber</p>
              <time>7:42 PM</time>
              <p className="chat-bubble ted accent">you’re 2,100 steps short. a 19-minute walk closes the gap. shoes on?</p>
              <p className="chat-bubble user short">Going now</p>
            </div>
          </div>
          <div className="story-notes"><article><span>01</span><h3>You report life as it happens.</h3><p>Meals, water, steps, workouts, and your own commitments—in text, photos, or voice notes.</p></article><article><span>02</span><h3>Ted keeps the running context.</h3><p>It compares the latest update with what you planned and everything already logged that day.</p></article><article><span>03</span><h3>You get one move, not a lecture.</h3><p>Specific enough to act on. Small enough to fit the day that actually happened.</p></article></div>
        </div>
      </section>

      <section className="remember-section">
        <div className="remember-clip page-shell">
          <div className="remember-heading"><p className="section-label">What Ted remembers</p><h2>Everything that makes<br />the next nudge useful.</h2></div>
          <div className="remember-list">
            <article><span>01</span><h3>Meals & nutrition</h3><p>Calories, protein, carbs, fat, and fiber from text, voice notes, or a clear meal photo.</p><b>+</b></article>
            <article><span>02</span><h3>Water & steps</h3><p>What you have done, what remains, and whether another reminder is worth sending.</p><b>+</b></article>
            <article><span>03</span><h3>Workouts</h3><p>Done, skipped, or realistically moved—never turned into punishment for eating.</p><b>+</b></article>
            <article><span>04</span><h3>Your commitments</h3><p>The routine written in your own words, with quiet hours and reminders you control.</p><b>+</b></article>
          </div>
          <div className="mascot-peek"><Image src={tedMascot} alt="Ted mascot" width={1024} height={1024} sizes="300px" /></div>
        </div>
      </section>

      <section className="review-section page-shell" aria-labelledby="review-title">
        <div className="review-copy"><p className="section-label">The screenshot moment</p><h2 id="review-title">An honest close.<br /><em>Not a perfect score.</em></h2><p>At your chosen evening time, Ted brings the day together and names the one thing still worth doing.</p></div>
        <div className="review-card">
          <div className="review-head"><SmallAvatar /><div><strong>Evening review</strong><small>Example · 10:30 PM</small></div><span>7:42</span></div>
          <p className="review-line">good recovery. the walk rescued the bit that was slipping.</p>
          <dl><div><dt>Meals</dt><dd>3 logged</dd><i /></div><div><dt>Water</dt><dd>2.4 / 2.5L</dd><i className="almost" /></div><div><dt>Steps</dt><dd>8,214</dd><i /></div><div><dt>Workout</dt><dd>Moved to Sat</dd><i className="moved" /></div></dl>
          <p className="review-next"><span>Tomorrow’s one move</span>Protein at breakfast, before the calendar starts misbehaving.</p>
        </div>
      </section>

      <section className="how-section" aria-labelledby="how-title"><div className="page-shell"><p className="section-label">How it works</p><h2 id="how-title">WhatsApp is the app.</h2><div className="how-grid"><article><span>1</span><h3>Start the chat</h3><p>No email, password, payment, or setup maze.</p></article><article><span>2</span><h3>Tell Ted your day</h3><p>Use text or voice for any update, and photos for meals.</p></article><article><span>3</span><h3>Get the next useful move</h3><p>See what’s done, what remains, and what still fits.</p></article></div><WhatsAppLink /></div></section>

      <section className="privacy-section page-shell" id="privacy" aria-labelledby="privacy-title">
        <div className="privacy-stamp"><span>your health.</span><span>your data.</span><strong>your call.</strong></div>
        <div className="privacy-copy-block"><p className="section-label">Before you start</p><h2 id="privacy-title">Personal should stay personal.</h2><p>Ted stores your profile, messages, plans, logs, and uploaded media so it can remember your day. Ted and the services that run it process this information.</p><p>Message “delete my data” and confirm to permanently remove your saved Ted data.</p><div className="safety-box"><strong>Adults 18+ only.</strong><span>Ted is a habit coach, not medical advice, and should not be used for emergencies, diagnosis, or treatment.</span></div><Link href="/privacy">Read the privacy policy <span aria-hidden="true">→</span></Link></div>
      </section>

      <section className="closing-section"><div className="page-shell"><p className="section-label light">Start where today is</p><h2>One message.<br /><em>Ted remembers the rest.</em></h2><WhatsAppLink label="Meet Ted on WhatsApp" /><p className="closing-note">Free during beta · 18+ · Opens WhatsApp</p><div className="closing-logo"><Logo /></div></div></section>
      <footer className="site-footer page-shell"><p>© 2026 Ted</p><p>Fitness accountability in WhatsApp.</p><Link href="/privacy">Privacy</Link></footer>
    </main>
  );
}
