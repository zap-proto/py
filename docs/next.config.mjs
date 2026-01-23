const isProd = process.env.NODE_ENV === 'production'

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  basePath: isProd ? '/zap-py' : '',
  assetPrefix: isProd ? '/zap-py/' : '',
  images: {
    unoptimized: true,
  },
  trailingSlash: true,
}

export default nextConfig
