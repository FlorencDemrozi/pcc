import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import obfuscatorPlugin from 'vite-plugin-javascript-obfuscator'

export default defineConfig({
  plugins: [
    react(),
    obfuscatorPlugin({
      options: {
        // ── Obfuscation strength ────────────────────────────────────────────
        // These settings give strong protection without breaking the app.
        // Higher rotationAmount / more dead code = slower load but harder to read.

        compact: true,                      // remove whitespace/newlines
        simplify: true,                     // simplify expressions
        splitStrings: true,                 // split string literals into pieces
        splitStringsChunkLength: 5,
        stringArray: true,                  // move strings to encrypted array
        stringArrayEncoding: ['base64'],    // encode the array
        stringArrayThreshold: 0.85,         // 85% of strings get obfuscated
        stringArrayIndexShift: true,
        stringArrayRotate: true,
        stringArrayShuffle: true,
        stringArrayWrappersCount: 2,
        stringArrayWrappersType: 'function',
        stringArrayWrappersChainedCalls: true,
        unicodeEscapeSequence: false,       // keep false — reduces file size

        identifierNamesGenerator: 'hexadecimal',  // names like _0x1a2b3c
        renameGlobals: false,               // keep false — breaks React globals
        renameProperties: false,            // keep false — breaks object access

        controlFlowFlattening: true,        // scramble control flow
        controlFlowFlatteningThreshold: 0.4, // 40% of blocks — balance vs size

        deadCodeInjection: true,            // inject unreachable fake code
        deadCodeInjectionThreshold: 0.2,    // 20% — keeps size reasonable

        debugProtection: false,             // keep false — breaks devtools legit use
        disableConsoleOutput: true,         // suppress console.log in production
        selfDefending: false,               // keep false — can break in some envs

        transformObjectKeys: true,          // obfuscate object property names
        numbersToExpressions: true,         // replace numbers with expressions
      },
      // lazyLibs.js holds the dynamic import() calls; obfuscating it would turn the
      // module specifiers into runtime strings the bundler cannot resolve.
      exclude: [/node_modules/, /lazyLibs\.js$/],
      // Only obfuscate the production build assets, not the dev server
      apply: 'build',
    }),
  ],
  server: {
    host: '127.0.0.1',   // never expose the dev proxy (and API keys) to the LAN
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    minify: 'terser',
    terserOptions: {
      compress: { drop_console: true, passes: 2 },
      mangle: { toplevel: true },
      format: { comments: false },
    },
  },
})
