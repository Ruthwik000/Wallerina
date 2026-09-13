// Flat ESLint config. `next lint` is removed in Next 15, so linting runs
// through the ESLint CLI directly — see the "lint" script in package.json.
import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({
  baseDirectory: dirname(fileURLToPath(import.meta.url)),
});

export default [
  ...compat.extends("next/core-web-vitals"),
  {
    ignores: [".next/**", "build/**", "node_modules/**", "next-env.d.ts"],
  },
];
