FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_HOST_MODE=demo
ENV VITE_HOST_MODE=${VITE_HOST_MODE} VITE_SURVEY_MODE=api VITE_API_ORIGIN=""
RUN npm run build

FROM nginx:alpine
USER root
RUN apk add --no-cache curl \
    && sed -i 's@^[[:space:]]*pid[[:space:]].*;@pid /tmp/nginx.pid;@' /etc/nginx/nginx.conf \
    && sed -i '/^user /d' /etc/nginx/nginx.conf \
    && chown -R 101:101 /var/cache/nginx
USER 101:101
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8443
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
