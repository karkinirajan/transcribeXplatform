import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits .next/standalone with a self-contained server.js plus only the
  // node_modules it actually needs. The desktop app runs that server with
  // Electron's built-in Node, so installers require no Node.js on the machine.
  output: "standalone",

  // The Python API is a separate process on 127.0.0.1:8000 in both dev and
  // packaged builds; proxying keeps the browser on a single origin.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
