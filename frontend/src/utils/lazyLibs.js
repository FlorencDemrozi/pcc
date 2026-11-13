// Lazy loaders for bundled third-party parsers (code-split via dynamic import()).
// NOTE: this file is excluded from javascript-obfuscator in vite.config.js —
// the obfuscator would otherwise rewrite the import() specifiers into runtime
// expressions that the bundler cannot resolve.

export const loadJSZip = () => import("jszip").then(m => m.default || m);
export const loadXLSX  = () => import("xlsx");
