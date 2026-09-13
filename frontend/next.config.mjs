/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  // Production builds get their own output directory.
  //
  // `next build` and `next dev` both default to `.next`, so a build run while
  // the dev server is up overwrites the chunks that server is holding open.
  // It fails as `Cannot find module './586.js'`, which points at nothing
  // useful and cost a debugging session before the cause was found.
  distDir: process.env.NODE_ENV === "production" ? ".next-build" : ".next",
};

export default nextConfig;
