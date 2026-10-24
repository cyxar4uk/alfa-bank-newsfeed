FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Пусто — сборка на тестовых данных. VITE_API_URL=/ — API через nginx этого же образа (см. API_UPSTREAM).
# VITE_API_LIVE — какие методы уже берутся из API (через запятую или all), остальное — тестовые данные.
ARG VITE_API_URL=
ARG VITE_API_LIVE=personas,company,health
ENV VITE_API_URL=$VITE_API_URL VITE_API_LIVE=$VITE_API_LIVE
RUN npm run build

FROM nginx:1.27-alpine
ENV API_UPSTREAM=http://api:8000
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
