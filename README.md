# TCF Pilates Telegram Takip Botu

Bu proje Turkiye Cimnastik Federasyonu Pilates duyurularini Vercel uzerinde tek seferlik bir serverless endpoint ile kontrol eder. Sonsuz dongu yoktur.

Vercel Cron kaldirildi. 5 dakikada bir tetikleme isi GitHub Actions ile yapilir.

## Endpointler

Ana endpoint:

[https://PROJECT_URL.vercel.app/api/cron](https://project_url.vercel.app/api/cron)

GitHub Actions icin alias endpoint:

```text
https://SENIN-VERCEL-URL.vercel.app/api/check
```

`api/check.py`, `api/cron.py` icindeki ayni handler'i kullanir.

## Vercel Deploy Notu

Vercel Python entrypoint'i `pyproject.toml` icinde tanimlidir:

```toml
[tool.vercel]
entrypoint = "api.cron:handler"
```

`vercel.json` su an bilerek bos objedir:

```json
{}
```

Bu sayede Hobby planda hata veren Vercel Cron tanimi deploy'a girmez.

## Kaynaklar

Ana kaynak:

```text
https://www.tcf.gov.tr/wp-json/wp/v2/posts?per_page=10&orderby=date&order=desc
```

Yedek kaynak:

```text
https://www.tcf.gov.tr/branslar/pilates/
```

## Bildirim Kurali

Post basligi, ozeti veya iceriginde su kosullar aranir:

- `Pilates` gecmeli
- `2. Kademe` gecmeli
- `Temel Egitmenlik`, `Temel Egitim` veya `Kursu` ifadelerinden biri gecmeli

Arama buyuk/kucuk harf duyarsiz yapilir. HTML etiketleri ve entity degerleri temizlenir.

## Durum Saklama

Tekrar bildirimleri engellemek icin Upstash Redis veya Vercel KV kullanilir.

Kullanilan anahtarlar:

- `tcf:last_processed_post_id`: WordPress API'de islenen son post id
- `tcf:notified_post:{id}`: Bildirimi gonderilmis postlar icin ek guvenlik anahtari
- `tcf:pilates_page_hash`: Pilates HTML sayfasinin son bildirilen hash degeri

`tcf:notified_post:{id}` anahtari `SET NX` ile yazildigi icin ayni post icin duplicate Telegram bildirimi gonderilmez.

## Kurulum

Python 3.10 veya uzeri gerekir.

```bash
pip install -r requirements.txt
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

`.env` dosyasini doldurun:

```env
TELEGRAM_BOT_TOKEN=123456789:telegram_bot_tokeniniz
TELEGRAM_CHAT_ID=123456789
UPSTASH_REDIS_REST_URL=https://example.upstash.io
UPSTASH_REDIS_REST_TOKEN=upstash_rest_tokeniniz
CRON_SECRET=
NOTIFY_EXISTING_ON_FIRST_RUN=false
```

Vercel KV kullaniyorsaniz `UPSTASH_*` yerine su degiskenleri de kullanabilirsiniz:

```env
KV_REST_API_URL=https://example.upstash.io
KV_REST_API_TOKEN=vercel_kv_tokeniniz
```

## Lokal Test

Tek seferlik kontrol:

```bash
python bot.py
```

Vercel API route'unu lokal test etmek icin:

```bash
vercel dev
```

Sonra:

```bash
curl http://localhost:3000/api/cron
curl http://localhost:3000/api/check
```

## GitHub Actions Ping

Workflow dosyasi:

```text
.github/workflows/ping.yml
```

Deploy'dan sonra workflow icindeki URL'yi kendi Vercel URL'inizle degistirin:

```yaml
run: curl -fsS https://SENIN-VERCEL-URL.vercel.app/api/check
```

Ornek:

```yaml
run: curl -fsS https://tcf-pilates-telegram-bot.vercel.app/api/check
```

## Vercel Environment Variables

Vercel Project Settings > Environment Variables bolumune su degerleri ekleyin:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `UPSTASH_REDIS_REST_URL`
- `UPSTASH_REDIS_REST_TOKEN`
- `CRON_SECRET` istege bagli; GitHub Actions curl komutu headersizse bos birakin
- `NOTIFY_EXISTING_ON_FIRST_RUN` istege bagli

## Telegram Mesaj Formati

```text
Yeni Pilates 2. Kademe Kurs Duyurusu!

Baslik: ...
Tarih: ...
Link: ...

Kisa ozet: ...
```

## Ilk Calistirma Davranisi

Varsayilan olarak ilk calistirmada mevcut son post id baslangic noktasi olarak kaydedilir ve eski duyurular icin bildirim gonderilmez. Ilk calistirmada mevcut eslesmeleri de bildirmek isterseniz:

```env
NOTIFY_EXISTING_ON_FIRST_RUN=true
```

## Hata Yonetimi

Route hata alirsa HTTP 500 JSON yaniti doner ve mumkunse Telegram'a hata mesaji gonderir. Bir sonraki GitHub Actions ping'i normal sekilde tekrar kontrol yapar.
