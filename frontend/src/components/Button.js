import Link from "next/link";
import styles from "./Button.module.css";

/**
 * @param {"primary"|"ghost"|"quiet"} variant
 */
export default function Button({
  children,
  variant = "primary",
  href,
  size = "md",
  full = false,
  ...rest
}) {
  const className = `${styles.button} ${styles[variant]} ${styles[size]} ${full ? styles.full : ""}`;

  if (href) {
    return (
      <Link href={href} className={className} {...rest}>
        {children}
      </Link>
    );
  }

  return (
    <button type="button" className={className} {...rest}>
      {children}
    </button>
  );
}
