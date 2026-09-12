import { Gideon_Roman, Open_Sans } from "next/font/google";
import "./globals.css";

const gideonRoman = Gideon_Roman({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-display",
  display: "swap",
});

const openSans = Open_Sans({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata = {
  title: "Wallerina",
  description:
    "Wallerina - Agents to make your wallet stable like a Ballerina",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={`${gideonRoman.variable} ${openSans.variable}`}>
      <body>{children}</body>
    </html>
  );
}
