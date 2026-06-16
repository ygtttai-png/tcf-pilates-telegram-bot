# TCF Pilates Telegram Takip Botu

Bu proje Turkiye Cimnastik Federasyonu Pilates duyurularini GitHub Actions ile takip eder. Vercel destegi yoktur; proje herhangi bir serverless endpoint calistirmaz.

GitHub Actions workflow'u her 5 dakikada bir `python bot.py` komutunu calistirir. Script tek sefer kontrol yapar ve kapanir. Infinite loop kullanmaz.

## Workflow

Workflow dosyasi:

```text
.github/workflows/check.yml
```

Workflow ozeti:

- Her 5 dakikada bir calisir: `*/5 * * * *`
- Manuel calistirma destekler: `workflow_dispatch`
- Python 3.11 kullanir.
- `pip install -r requirements.txt` calistirir.
- `python bot.py` calistirir.
- GitHub Actions loglarinda UTC zamanini, event bilgisini, Python surumunu ve secret durumlarini `Present / Missing` olarak yazar.

GitHub Actions bazen yeni schedule workflow'larini Actions sekmesinde ilk run olana kadar gec gosterebilir. Hemen test etmek icin Actions sekmesinden `Check TCF Pilates` workflow'unu acip `Run workflow` ile manuel calistirin.

## GitHub Secrets

Repo ayarlarindan `Settings > Secrets and variables > Actions > New repository secret` bolumune su secret'lari ekleyin:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `UPSTASH_REDIS_REST_URL`
- `UPSTASH_REDIS_REST_TOKEN`

Workflow env bloklari bu secret'lari su sekilde kullanir:

```yaml
TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
UPSTASH_REDIS_REST_URL: ${{ secrets.UPSTASH_REDIS_REST_URL }}
UPSTASH_REDIS_REST_TOKEN: ${{ secrets.UPSTASH_REDIS_REST_TOKEN }}
```

Secret degerleri loglara yazdirilmaz. Sadece `Present` veya `Missing` bilgisi gosterilir.

## Kaynak

Bot once WordPress API'yi dener:

```text
https://www.tcf.gov.tr/wp-json/wp/v2/posts?per_page=10&orderby=date&order=desc
```

Bot WordPress JSON cevabinda su alanlari kontrol eder:

- `title.rendered`
- `excerpt.rendered`
- `content.rendered`

WordPress API 403 veya baska bir hata verirse HTML fallback kullanilir:

```text
https://www.tcf.gov.tr/branslar/pilates/
```

TCF istekleri browser-like headers ve `requests.Session` ile yapilir.

## Bildirim Kurali

Baslik, ozet veya icerikte su kosullar birlikte aranir:

- `Pilates` gecmeli
- `2. Kademe` gecmeli
- `Temel Egitmenlik`, `Temel Egitim` veya `Kursu` ifadelerinden biri gecmeli

Arama buyuk/kucuk harf duyarsiz yapilir. HTML etiketleri ve entity degerleri temizlenir.

## Duplicate Engelleme

Tekrar bildirimleri engellemek icin Upstash Redis kullanilir.

Kullanilan anahtarlar:

- `tcf:last_processed_post_id`: Islenen son WordPress post id
- `tcf:notified_post:{id}`: Bildirimi gonderilmis postlar icin ek guvenlik anahtari
- `tcf:html_fallback:{hash}`: HTML fallback eslesmeleri icin duplicate engelleme anahtari
- `tcf:startup_notified`: Ilk basarili workflow bildiriminin gonderildigini tutar
- `tcf:last_error_state`: Son hata durumunu tutar
- `tcf:error_reported:{hash}`: Ayni hatayi 6 saat icinde tekrar bildirmemek icin kullanilir

`tcf:notified_post:{id}` ve hata throttle anahtarlari Redis `SET NX` ile yazilir.

`UPSTASH_REDIS_REST_URL` mutlaka Upstash REST URL olmali ve `https://` ile baslamalidir. `redis://...` endpoint'i kullanilirsa bot acik bir hata verir:

```text
UPSTASH_REDIS_REST_URL must be the Upstash REST URL starting with https://, not the redis:// endpoint.
```

## Startup Bildirimi

Ilk basarili workflow calismasinda Telegram'a su mesaj gonderilir:

```text
✅ TCF Pilates Bot Started

UTC time: ...
Telegram token: Present
Redis URL: Present
Redis token: Present
Source used: WordPress API
```

Secret degerleri hicbir zaman yazdirilmaz.

## Health Monitoring

Bot hata alirsa:

- Hata GitHub Actions loglarina yazilir.
- Mumkunse Telegram'a hata mesaji gonderilir.
- Ayni hata en fazla 6 saatte bir bildirilir.
- Hata durumu Redis'e kaydedilir.

Bot sonraki calismada basariyla toparlanirsa Telegram'a su mesaj gonderilir:

```text
✅ Bot recovered successfully
```

## Lokal Kurulum

Python 3.10 veya uzeri gerekir.

```bash
pip install -r requirements.txt
cp .env.example .env
python bot.py
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
python bot.py
```

`.env` dosyasini doldurun:

```env
TELEGRAM_BOT_TOKEN=123456789:telegram_bot_tokeniniz
TELEGRAM_CHAT_ID=123456789
UPSTASH_REDIS_REST_URL=https://example.upstash.io
UPSTASH_REDIS_REST_TOKEN=upstash_rest_tokeniniz
```

## Ilk Calistirma Davranisi

Varsayilan olarak ilk calistirmada mevcut son post id baslangic noktasi olarak kaydedilir ve eski duyurular icin bildirim gonderilmez.

Eski son 10 post icindeki eslesmeleri de ilk calistirmada bildirmek isterseniz workflow veya lokal ortam icin su env degerini ekleyebilirsiniz:

```env
NOTIFY_EXISTING_ON_FIRST_RUN=true
```

## Telegram Kurs Mesaj Formati

```text
🚨 Yeni Pilates 2. Kademe Kurs Duyurusu!

Başlık: ...
Tarih: ...
Link: ...

Kısa özet: ...
```
