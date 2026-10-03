/** @type {import('next').NextConfig} */
const nextConfig = {
  // Emits .next/standalone so the Docker image ships without node_modules
  output: "standalone",
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  // WalletConnect's dependencies probe for these optional modules at runtime;
  // marking them external stops webpack warning about each one on every build.
  webpack: (config) => {
    config.externals.push("pino-pretty", "lokijs", "encoding")
    return config
  },
}

export default nextConfig
