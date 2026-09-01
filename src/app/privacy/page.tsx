import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy | Ted",
  description: "What Ted stores, who can see it, how long it is kept, and how to delete it.",
};

export default function PrivacyPage() {
  return (
    <main className="privacy-page">
      <header className="privacy-header page-shell">
        <Link className="brand" href="/" aria-label="Ted home">Ted<span className="brand-dot" aria-hidden="true">.</span></Link>
        <Link className="privacy-back" href="/">Back to Ted</Link>
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
          <p>Send <strong>delete my data</strong> in your Ted WhatsApp chat. Ted will ask you to confirm once. After you confirm, Vandy will delete your profile, plans, logs, uploads, reminders, reviews, and conversation history.</p>
        </section>

        <p className="privacy-boundary">Ted is a habit coach, not a doctor. Do not use it for emergencies, diagnosis, or treatment.</p>
      </article>
    </main>
  );
}
