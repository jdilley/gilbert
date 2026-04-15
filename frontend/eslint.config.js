// ESLint flat config for the Gilbert frontend (React 19 + TS + Vite).
//
// Minimal setup: typescript-eslint recommended rules + react-hooks +
// react-refresh, scoped to src/. Kept deliberately light — this repo
// doesn't want lint to fight the existing code, just to catch real
// bugs (unused vars, bad hook deps, shadowed names, react-refresh
// violations that break HMR) that aren't already caught by tsc.

import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  // Skip build outputs and generated SPA bundle.
  { ignores: ["dist/**", "node_modules/**", "**/*.generated.*"] },
  {
    files: ["src/**/*.{ts,tsx}"],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommended,
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Vite HMR requires that hot-reloadable modules only export
      // React components. This rule catches util exports mixed into
      // a component module, which silently break fast-refresh.
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
      // Underscore-prefixed vars are conventionally "intentionally
      // unused" — match Python's ``_`` convention and don't warn.
      "@typescript-eslint/no-unused-vars": [
        "warn",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
        },
      ],
      // ── Rules downgraded to warnings on first eslint setup ─────
      //
      // These are real issues in the current tree (some strict
      // enough to surface genuine React 19 / TypeScript concerns)
      // that the wider codebase hasn't been audited for yet.
      // Downgraded to ``warn`` so ``npm run lint`` exits 0 out of
      // the box instead of blocking every dev loop on a pre-
      // existing issue. Tighten to ``error`` once the backlog is
      // cleaned up.
      //
      // - set-state-in-effect: 5 sites in useMediaQuery,
      //   useWebSocket, etc. where a useEffect body calls setState
      //   directly; usually safe but can cause cascading renders.
      // - static-components / refs: flags factories that create
      //   components mid-render (intentional memoized patterns in
      //   UIBlockRenderer and a few hooks). Review case-by-case.
      // - rules-of-hooks: 2 conditional hook calls that need
      //   refactoring to unconditional.
      // - no-explicit-any: 2 sites in useWebSocket typed as
      //   ``any`` for framework interop.
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/static-components": "warn",
      "react-hooks/refs": "warn",
      "react-hooks/rules-of-hooks": "warn",
      "@typescript-eslint/no-explicit-any": "warn",
    },
  },
);
