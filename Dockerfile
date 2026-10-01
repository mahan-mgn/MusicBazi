# فرانت موزیک بازی — بیلد با Vite، سرو با nginx
FROM node:22-alpine AS build

WORKDIR /app

# لایه‌ی جدا برای وابستگی‌ها: تغییر کد نباید npm ci را دوباره اجرا کند
COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src
# آیکون‌های PWA، favicon و سرویس‌ورکرِ آفلاین اینجا زندگی می‌کنند. بدون این
# خط، بیلدِ داکر بی‌صدا بدونشان تمام می‌شد: مانیفست به آیکون‌هایی اشاره می‌کرد
# که ۴۰۴ می‌دادند و «افزودن به صفحه‌ی اصلی» روی موبایل یا آیکون خالی می‌ساخت
# یا اصلاً پیشنهاد نمی‌شد.
COPY public ./public

# در داکر فرانت همیشه به بک‌اند واقعی وصل است؛ مود ماک فقط برای دِو محلی است
ENV VITE_API_MODE=http
RUN npm run build


FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
