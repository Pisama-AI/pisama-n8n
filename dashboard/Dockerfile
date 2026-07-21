# Self-host dashboard image. NEXT_PUBLIC_* values are baked at BUILD time (they
# are inlined into the client bundle), so pass them as build args, not runtime env:
#   docker build --build-arg NEXT_PUBLIC_API_BASE=http://localhost:8400 -t pisama-n8n-dashboard .
# NEXT_PUBLIC_API_BASE is the server URL the BROWSER fetches (default matches the
# docker-compose port mapping, where the server is published on the host at :8400).
FROM node:22-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG NEXT_PUBLIC_API_BASE=http://localhost:8400
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
RUN npm run build
ENV NODE_ENV=production
EXPOSE 3000
CMD ["npm", "start"]
