import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy | Ted",
  description: "What Ted stores, who can see it, how long it is kept, and how to delete it.",
};

/** The landing page's Ted mark, redrawn here so /privacy opens with the same
 *  logo rather than a wordmark from the design it replaced. */
function TedLogo() {
  return (
    <span className="ted-logo">
      <svg className="bubble" viewBox="4 2 44 45" aria-hidden="true">
        <rect x="4" y="2" width="44" height="34" rx="10" fill="#ff7e3e" />
        <path d="M13 34 L7 47 L24 35 Z" fill="#ff7e3e" />
        <g fill="none" stroke="#111317" strokeWidth="2.9" strokeLinecap="round">
          <path d="M15 16 Q19 9.5 23 16" />
          <path d="M29 16 Q33 9.5 37 16" />
          <path d="M17 22 Q26 32 35 22" />
        </g>
      </svg>
      <span className="wm"><b>t</b><b>e</b><b>d</b></span>
    </span>
  );
}

export default function PrivacyPage() {
  return (
    <main className="privacy-page">
      <header className="privacy-header page-shell">
        <Link className="brand" href="/" aria-label="Ted home"><TedLogo /></Link>
        <Link className="privacy-back" href="/">Back to Ted <span aria-hidden="true">→</span></Link>
      </header>

      <article className="privacy-copy page-shell">
        <p className="eyebrow">Privacy</p>
        <h1>Your health data stays your call.</h1>
        <p className="privacy-intro">This page explains what happens to the information you share with Ted during the beta.</p>

        <section>
          <h2>What is stored</h2>
          <p>Ted stores your name, goals, targets, reminders, messages, meal and activity logs, uploaded plans, photos, voice notes, documents, and the daily or weekly reviews it creates for you.</p>
        </section>

        <section>
          <h2>Who can see it</h2>
          <p>Vandy, who runs this beta, can access the data to operate and fix Ted. Hermes, WhatsApp, the AI model provider, Vercel, and Convex process the parts they need to run the chat, website, and storage. Other testers cannot see your information.</p>
        </section>

        <section>
          <h2>How long it is kept</h2>
          <p>Your profile, conversations, logs, and original uploads are kept until you ask for deletion. Ted does not use your health information for advertising.</p>
        </section>

        <section>
          <h2>How to delete it</h2>
          <p>Send <strong>delete my data</strong> in your Ted WhatsApp chat. Ted will ask you to confirm once. As soon as you confirm, Ted deletes everything it has stored about you: your profile, saved facts, targets, reminders, and every logged meal, workout, and daily entry. That happens immediately and cannot be undone.</p>
          <p>Two things sit outside that automatic deletion, and we would rather say so than let you assume otherwise. The photos and voice notes you sent, and Ted&rsquo;s own record of your conversation, are held on the machine that runs Ted; reply in the chat asking for those to be removed and Vandy will delete them by hand. The WhatsApp chat on your own phone belongs to you &mdash; clearing it there is yours to do.</p>
        </section>

        <section>
          <h2>How to reach us</h2>
          <p>Message Ted in your WhatsApp chat for anything about your data &mdash; a question, a correction, a deletion, or a complaint. Vandana Agarwal runs this beta independently and reads those messages. Say <strong>this is for Vandy</strong> at the start and Ted will pass it on rather than coach you about it.</p>
          <p>The chat is the only contact route during the private beta, so keep it if you may want to reach us later: once you delete the chat on your own phone, and Ted has deleted your data, there is nothing left connecting you to us.</p>
        </section>

        <p className="privacy-boundary">Ted is a habit coach, not a doctor. Do not use it for emergencies, diagnosis, or treatment.</p>
      </article>

      <footer className="privacy-footer page-shell">
        <span>© 2026 Ted</span>
        <span>A habit coach, not medical advice — not for emergencies, diagnosis or treatment</span>
        <Link href="/">heyted.vercel.app</Link>
      </footer>
    </main>
  );
}
