import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import mdx from '@astrojs/mdx';
export default defineConfig({
  // ...
  integrations: [react(), mdx()],
  vite: {
    plugins: [{
      name: 'separate-dev-build-cache',
      config(_config, { command }) {
        // Builds must not replace React dependencies used by a running dev server.
        return { cacheDir: `node_modules/.vite-${command}` };
      },
    }],
  },
  site: 'https://eva-zh-hans.github.io',
  base: '/nge_2_re'
});
