import styles from "./Panel.module.css";

/**
 * The single container used across the application. Every page is a grid of
 * these — there are no other surface treatments.
 */
export default function Panel({ title, meta, action, children, flush = false, className = "" }) {
  return (
    <section className={`${styles.panel} ${className}`}>
      {(title || action) && (
        <header className={styles.header}>
          <div>
            <h2 className={styles.title}>{title}</h2>
            {meta && <p className={styles.meta}>{meta}</p>}
          </div>
          {action && <div className={styles.action}>{action}</div>}
        </header>
      )}
      <div className={flush ? styles.bodyFlush : styles.body}>{children}</div>
    </section>
  );
}
