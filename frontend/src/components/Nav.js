"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import styles from "./Nav.module.css";

const SECTIONS = [
  {
    title: "Overview",
    items: [
      { href: "/dashboard", label: "Dashboard" },
      { href: "/portfolio", label: "Portfolio" },
    ],
  },
  {
    title: "Analysis",
    items: [
      { href: "/risk", label: "Risk" },
      { href: "/simulations", label: "Simulations" },
      { href: "/recommendations", label: "Recommendations" },
    ],
  },
  {
    title: "Account",
    items: [{ href: "/settings", label: "Settings" }],
  },
];

export default function Nav() {
  const pathname = usePathname();

  return (
    <nav className={styles.nav} aria-label="Primary">
      <Link href="/" className={styles.brand}>
        <Image
          className={styles.logo}
          src="/logo.png"
          alt=""
          width={40}
          height={40}
          priority
        />
        <span className={styles.wordmark}>Wallerina</span>
      </Link>

      <div className={styles.sections}>
        {SECTIONS.map((section) => (
          <div key={section.title} className={styles.section}>
            <p className={styles.sectionTitle}>{section.title}</p>
            <ul className={styles.list}>
              {section.items.map((item) => {
                const active = pathname === item.href;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className={`${styles.link} ${active ? styles.active : ""}`}
                      aria-current={active ? "page" : undefined}
                    >
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>

      <p className={styles.footer}>
        Quantitative engine v0.1
        <br />
        Analysis is not financial advice
      </p>
    </nav>
  );
}
