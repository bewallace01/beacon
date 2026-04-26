FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json ./
RUN npm install --no-audit --no-fund

FROM node:20-alpine AS build
WORKDIR /app
ARG NEXT_PUBLIC_BEACON_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_BEACON_API_KEY=demo-key
ENV NEXT_PUBLIC_BEACON_API_URL=$NEXT_PUBLIC_BEACON_API_URL
ENV NEXT_PUBLIC_BEACON_API_KEY=$NEXT_PUBLIC_BEACON_API_KEY
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
