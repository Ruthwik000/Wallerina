import Nav from "@/components/Nav";
import TopBar from "@/components/TopBar";
import { recommendation } from "@/lib/data";
import styles from "./shell.module.css";

export default function AppLayout({ children }) {
  return (
    <div className={styles.shell}>
      <Nav />
      <div className={styles.main}>
        <TopBar lastAnalysis={recommendation.generatedAt} />
        <main className={styles.content}>{children}</main>
      </div>
    </div>
  );
}
