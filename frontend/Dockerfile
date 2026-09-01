FROM node:22-alpine AS build

WORKDIR /app

ARG VITE_API_BASE_URL=
ARG VITE_AZURE_AD_CLIENT_ID=
ARG VITE_AZURE_AD_TENANT_ID=
ARG VITE_AZURE_AD_REDIRECT_URI=http://localhost:5173
ARG VITE_AZURE_AD_POST_LOGOUT_REDIRECT_URI=http://localhost:5173/login

ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_AZURE_AD_CLIENT_ID=$VITE_AZURE_AD_CLIENT_ID \
    VITE_AZURE_AD_TENANT_ID=$VITE_AZURE_AD_TENANT_ID \
    VITE_AZURE_AD_REDIRECT_URI=$VITE_AZURE_AD_REDIRECT_URI \
    VITE_AZURE_AD_POST_LOGOUT_REDIRECT_URI=$VITE_AZURE_AD_POST_LOGOUT_REDIRECT_URI

COPY package.json package-lock.json ./
RUN npm ci

COPY index.html vite.config.ts tsconfig.json tsconfig.app.json tsconfig.node.json ./
COPY public ./public
COPY src ./src

RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
