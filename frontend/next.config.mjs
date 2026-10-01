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
}

export default nextConfig
