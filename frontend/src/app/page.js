import Image from "next/image";
import Link from "next/link";
import styles from "./landing.module.css";

export default function LandingPage() {
  return (
    <div className={styles.page}>
      <Image
        className={styles.backdrop}
        src="/background.png"
        alt=""
        fill
        priority
        sizes="100vw"
      />
      <div className={styles.veil} />

      <header className={styles.head}>
        <Link href="/" className={styles.brand} aria-label="Wallerina">
          <Image
            className={styles.logo}
            src="/logo.png"
            alt=""
            width={64}
            height={64}
            priority
          />
        </Link>
      </header>

      <main className={styles.hero}>
        <h1 className={styles.title}>Wallerina</h1>
        <p className={styles.tagline}>
          Wallerina — Agents to make your wallet stable like a Ballerina
        </p>

        <div className={styles.actions}>
          <Link href="/dashboard" className={styles.primary}>
            Connect Wallet
          </Link>
          <Link href="/dashboard" className={styles.secondary}>
            Enter Dashboard
          </Link>
        </div>
      </main>
    </div>
  );
}
