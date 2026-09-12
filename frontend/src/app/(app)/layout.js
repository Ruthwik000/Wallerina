import Nav from "@/components/Nav";
import TopBar from "@/components/TopBar";
import styles from "./shell.module.css";

export default function AppLayout({ children }) {
  return (
    <div className={styles.shell}>
      <Nav />
      <div className={styles.main}>
        <TopBar />
        <main className={styles.content}>{children}</main>
      </div>
    </div>
  );
}
