# TCF Pilates Telegram Takip Botu

Bu proje Türkiye Cimnastik Federasyonu Pilates duyurularını Vercel üzerinde takip eder. Vercel Cron `/api/cron` route'unu her 5 dakikada bir çağırır; route WordPress API'yi ve Pilates HTML sayfasını kontrol eder, eşleşme varsa Telegram'a bildirim gönderir.

Sonsuz döngü yoktur. Her cron çağrısı tek kontrol yapıp kapanır.

## Kaynaklar

Ana kaynak:

```text
https://www.tcf.gov.tr/wp-json/wp/v2/posts?per_page=10&orderby=date&order=desc
```

Yedek kaynak:

```text
https://www.tcf.gov.tr/branslar/pilates/
```

## Bildirim Kuralı

Post başlığı, özeti veya içeriğinde şu koşullar aranır:

- `Pilates` geçmeli
- `2. Kademe` geçmeli
- `Temel Eğitmenlik`, `Temel Eğitim` veya `Kursu` ifadelerinden biri geçmeli

Arama büyük/küçük harf duyarsız yapılır. HTML etiketleri ve entity değerleri temizlenir.

## Durum Saklama

Tekrar bildirimleri engellemek için Upstash Redis veya Vercel KV kullanılır.

Kullanılan anahtarlar:

- `tcf:last_processed_post_id`: WordPress API'de işlenen son post id
- `tcf:notified_post:{id}`: Bildirimi gönderilmiş postlar için ek güvenlik anahtarı
- `tcf:pilates_page_hash`: Pilates HTML sayfasının son bildirilen hash değeri

`tcf:notified_post:{id}` anahtarı `SET NX` ile yazıldığı için aynı post için duplicate Telegram bildirimi gönderilmez.

## Kurulum

Python 3.10 veya üzeri gerekir.

```bash
pip install -r requirements.txt
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

`.env` dosyasını doldurun:

```env
TELEGRAM_BOT_TOKEN=123456789:telegram_bot_tokeniniz
TELEGRAM_CHAT_ID=123456789
UPSTASH_REDIS_REST_URL=https://example.upstash.io
UPSTASH_REDIS_REST_TOKEN=upstash_rest_tokeniniz
CRON_SECRET=uzun_rastgele_bir_deger
NOTIFY_EXISTING_ON_FIRST_RUN=false
```

Vercel KV kullanıyorsanız `UPSTASH_*` yerine şu değişkenleri de kullanabilirsiniz:

```env
KV_REST_API_URL=https://example.upstash.io
KV_REST_API_TOKEN=vercel_kv_tokeniniz
```

## Lokal Test

Tek seferlik kontrol:

```bash
python bot.py
```

Vercel API route'unu lokal test etmek için:

```bash
vercel dev
```

Sonra:

```bash
curl -H "Authorization: Bearer uzun_rastgele_bir_deger" http://localhost:3000/api/cron
```

## Vercel Deploy

1. Projeyi Vercel'e deploy edin.
2. Vercel Project Settings > Environment Variables bölümüne şu değerleri ekleyin:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `UPSTASH_REDIS_REST_URL`
- `UPSTASH_REDIS_REST_TOKEN`
- `CRON_SECRET`
- `NOTIFY_EXISTING_ON_FIRST_RUN` isteğe bağlı

3. `vercel.json` içindeki cron ayarı route'u her 5 dakikada bir tetikler:

```json
{
  "crons": [
    {
      "path": "/api/cron",
      "schedule": "*/5 * * * *"
    }
  ]
}
```

## Telegram Mesaj Formatı

```text
🚨 Yeni Pilates 2. Kademe Kurs Duyurusu!

Başlık: ...
Tarih: ...
Link: ...

Kısa özet: ...
```

## İlk Çalıştırma Davranışı

Varsayılan olarak ilk çalıştırmada mevcut son post id başlangıç noktası olarak kaydedilir ve eski duyurular için bildirim gönderilmez. İlk çalıştırmada mevcut eşleşmeleri de bildirmek isterseniz:

```env
NOTIFY_EXISTING_ON_FIRST_RUN=true
```

## Hata Yönetimi

Route hata alırsa kapanmaz; HTTP 500 JSON yanıtı döner ve mümkünse Telegram'a hata mesajı gönderir. Bir sonraki Vercel Cron çağrısı normal şekilde tekrar kontrol yapar.
