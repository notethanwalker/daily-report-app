import type {NextConfig} from "next";

const securityHeaders=[
  {key:"X-Content-Type-Options",value:"nosniff"},
  {key:"X-Frame-Options",value:"DENY"},
  {key:"Referrer-Policy",value:"strict-origin-when-cross-origin"},
  {key:"Permissions-Policy",value:"camera=(), microphone=(), geolocation=()"},
];

const nextConfig:NextConfig={
  env:{
    NEXT_PUBLIC_API_BASE_URL:"/backend",
  },
  async headers(){return [{source:"/:path*",headers:securityHeaders}]},
};

export default nextConfig;
