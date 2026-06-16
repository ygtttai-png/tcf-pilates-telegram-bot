# TCF Pilates Telegram Takip Botu

Bu proje Turkiye Cimnastik Federasyonu Pilates duyurularini GitHub Actions ile takip eder. Vercel destegi yoktur; proje herhangi bir serverless endpoint calistirmaz.

GitHub Actions workflow'u her 5 dakikada bir `python bot.py` komutunu calistirir. Script tek sefer kontrol yapar ve kapanir. Infinite loop kullanmaz.

## Kaynak

```text
https://www.tcf.gov.tr/wp-json/wp/v2/posts?per_page=10&orderby=date&order=desc
```

Bot WordPress JSON cevabinda su alanlari kontrol eder:

- `title.rendered`
- `excerpt.rendered`
- `content.rendered`

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

`tcf:notified_post:{id}` anahtari Redis `SET NX` ile yazilir. Bu nedenle ayni post icin tekrar Telegram bildirimi gonderilmez.

## GitHub Secrets

Repo ayarlarindan `Settings > Secrets and variables > Actions > New repository secret` bolumune su secret'lari ekleyin:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `UPSTASH_REDIS_REST_URL`
- `UPSTASH_REDIS_REST_TOKEN`

## GitHub Actions

Workflow dosyasi:

```text
.github/workflows/check.yml
```

Workflow:

- Her 5 dakikada bir calisir.
- Manuel calistirma icin `workflow_dispatch` destekler.
- Python 3.11 kullanir.
- `pip install -r requirements.txt` calistirir.
- `python bot.py` calistirir.

Env degerleri workflow icinde GitHub Secrets uzerinden gecilir:

```yaml
env:
  TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
  TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
  UPSTASH_REDIS_REST_URL: ${{ secrets.UPSTASH_REDIS_REST_URL }}
  UPSTASH_REDIS_REST_TOKEN: ${{ secrets.UPSTASH_REDIS_REST_TOKEN }}
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

## Telegram Mesaj Formati

```text
Yeni Pilates 2. Kademe Kurs Duyurusu!

Baslik: ...
Tarih: ...
Link: ...

Kisa ozet: ...
```

## Hata Yonetimi

Kontrol sirasinda hata olursa script hata loglar, mumkunse Telegram'a hata mesaji yollar ve GitHub Actions job'u fail olur.
