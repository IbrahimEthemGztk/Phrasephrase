# PhrasePhrase — Proje Planı ve Claude Code Talimatları

Bu dosya, **PhrasePhrase** adlı web uygulamasının tüm ürün ve teknik detaylarını içerir. Claude Code içinde çalışırken bu dosyayı referans olarak kullan; her fazı ayrı ayrı Claude Code'a vererek adım adım ilerle (hepsini tek seferde yaptırmaya gerek yok).

---

## 1. Proje Özeti

**Proje adı:** PhrasePhrase

**Amaç:** Yeni bir dil öğrenen kullanıcıların, dil bilgisi kuralları veya tek tek kelime ezberi yerine, günlük hayatta kullanılan **kalıp cümleleri, atasözlerini ve deyimleri** akılda kalıcı görsel/sessel çağrışım (mnemonic) teknikleriyle ezberlemesini sağlamak.

**Kapsam dışı (bilinçli olarak):** Dil bilgisi anlatımı, kelime kartı (flashcard) tarzı tekil kelime öğrenimi, çeviri pratiği gibi klasik dil öğrenme özellikleri. Uygulama sadece "phrase" (kalıp ifade) ezberine odaklanır.

**İlk hedef dil:** Sadece İngilizce (öğrenilecek dil İngilizce; ileride başka dillere genişletilebilir, ama şimdilik tek dil).

**Proje felsefesi:** İlk aşamada **çalışan bir prototip** çıkarmak öncelik. Gereksiz karmaşık altyapılardan kaçınılacak, iterasyonlarla geliştirilecek.

---

## 2. Çekirdek Konsept: Mnemonic Phrase Yapısı

Uygulamanın kalbi, her phrase için şu 4 bileşenden oluşan bir "hafıza kartı":

1. **Abstract (Orijinal cümle + çevirisi):** Öğrenilecek dildeki cümle ve anlamı.
2. **Image / Breakdown (Sesli parçalama):** Cümlenin kelime kelime, ana dile yakın sesteş karşılıklarına bölünmesi.
3. **Association (Çağrışım hikayesi):** Bu ses parçalarını birbirine bağlayan, akılda kalıcı, mizahi/görsel bir mini hikaye.

### Örnekler

**Örnek 1 (Çince):**
- Abstract: `Nǐ hǎo ma` → "How are you?"
- Image: Nǐ (knee) — hǎo (how) — ma (ma: anne anlamında)
- Association: "Masaya 'diz'ini (knee) çarptın ve acıyla bağırdın. Arkandan bir ses 'Nasıl (how)' yaptın diye soruyor. Döndüğünde bunun 'anne'n (ma)' olduğunu görüyorsun, o da sana 'How are you?' diyor."

**Örnek 2 (Fransızca):**
- Abstract: `Comment allez-vous?` → "How are you?"
- Image: Comment (comment/yorum) — allez (Ali) — vous (sen/vous)
- Association: "'Ali'ye çok komik bir 'yorum (comment)' yapıldı. Döndü ve yorumu yapan kişiye 'How are you?' diye sordu."

### ⚠️ Kritik Teknik Kural: Kelime Sırası Korunmalı

Bu üç bileşen (orijinal kelimeler, ses karşılıkları, hikaye) **veri modelinde ve arayüzde her zaman birebir aynı sırada** tutulmalı ve gösterilmelidir. Yani "Image" kısmı serbest metin olarak değil, **orijinal cümledeki kelime sırasına göre sıralı bir liste (array)** olarak saklanmalı:

```json
{
  "original_phrase": "Nǐ hǎo ma",
  "translation": "How are you?",
  "word_breakdown": [
    { "order": 1, "original_word": "Nǐ", "sound_hint": "knee" },
    { "order": 2, "original_word": "hǎo", "sound_hint": "how" },
    { "order": 3, "original_word": "ma", "sound_hint": "ma (as in mother)" }
  ],
  "association_story": "Masana dizini çarptın..."
}
```

Bu sayede arayüzde kelimeler ve ses karşılıkları yan yana, sırayla ve hizalı gösterilebilir (örn. bir tabloda alt alta ya da yan yana kartlar halinde). Bu kural **tüm fazlarda** (manuel giriş, AI ile otomatik üretim, veritabanı şeması, frontend render) geçerlidir.

---

## 3. Kullanıcı Akışı (User Flow)

1. Kullanıcı siteye girer → kayıt olmamışsa **kayıt ol / giriş yap** ekranına yönlendirilir.
2. E-posta + parola ile kayıt olur (giriş de aynı şekilde).
3. Giriş yaptıktan sonra ana ekrana düşer: kendi **phrase havuzu** (henüz phrase yoksa boş durum / onboarding mesajı).
4. Kullanıcı "+ Ekle" butonuna basar. İki seçenek sunulur:
   - **Manuel giriş:** Kullanıcı kendi phrase'ini, kelime kelime ses karşılıklarını ve hikayesini kendisi yazar.
   - **Otomatik üretim (AI):** Kullanıcı sadece öğrenmek istediği İngilizce cümleyi/deyimi girer, sistem arka planda AI ile kelime kelime ses karşılığı + çağrışım hikayesi üretir. Kullanıcı üretilen sonucu onaylar/düzenler, sonra kaydeder.
5. Ana ekranda phrase'ler **kart yığını (swipe/kaydırma arayüzü)** olarak gösterilir:
   - Karta dokunarak/çevirerek Abstract → Image → Association aşamaları görülebilir (veya hepsi tek kartta gösterilir, bkz. Faz 3).
   - Kullanıcı kartı **sağa kaydırırsa** → "ezberledim" (öğrenildi).
   - Kullanıcı kartı **sola kaydırırsa** → "henüz ezberlemedim" (öğrenilmedi), bu kart tekrar kuyruğa (ezberlenmemişler sırasına) girer ve tekrar tekrar karşısına çıkmaya devam eder.
6. Kullanıcı istediği zaman kendi phrase havuzunu, öğrenilen/öğrenilmeyen istatistiklerini görebilir (ileri faz).

---

## 4. Teknik Yığın

| Katman | Teknoloji |
|---|---|
| Backend | Python + Django |
| Veritabanı | Supabase (PostgreSQL) |
| Kimlik doğrulama | Supabase Auth (e-posta + parola) *veya* Django auth + Supabase sadece DB olarak — bkz. Faz 1 notu |
| Frontend | Saf HTML, CSS, JavaScript (aynı Django repo'su içinde, ayrı bir frontend framework YOK — React/Vue/Next.js kullanılmayacak) |
| AI / Chatbot (otomatik phrase üretimi) | LLM API (Anthropic Claude API veya OpenAI API) — prompt ile yapılandırılmış JSON çıktı üretilecek |
| Deployment | Vercel |

### ⚠️ Vercel + Django Uyarısı

Vercel, doğası gereği Next.js/serverless odaklı bir platformdur. Django gibi bir WSGI uygulamasını Vercel'de çalıştırmak mümkündür ancak ekstra yapılandırma gerektirir (örn. `vercel.json` içinde Python runtime tanımı, statik dosyaların ayrı servis edilmesi, veritabanı bağlantılarının serverless/cold-start ile uyumlu olması). Claude Code'a Faz 0'da bu konuyu özellikle sorup en uygun (ör. `@vercel/python` runtime ya da WSGI adaptörü) kurulumu yapmasını iste. Eğer prototip aşamasında ciddi sorun çıkarsa alternatif olarak Railway/Render gibi Django'ya daha native destek veren bir platform da değerlendirilebilir — ama ilk denemede Vercel ile devam edilecek.

---

## 5. Veri Modeli (Taslak)

### `User` (Supabase Auth üzerinden veya Django `auth.User` + Supabase senkron)
- id
- email
- password (hashlenmiş)
- created_at

### `Phrase`
- id
- user_id (FK → User, sahibi)
- original_phrase (metin, örn: "Nǐ hǎo ma")
- translation (metin, örn: "How are you?")
- word_breakdown (JSON array, sıralı — bkz. Bölüm 2)
  - her eleman: `{ order, original_word, sound_hint }`
- association_story (metin)
- source (enum: `manual` / `ai_generated`)
- created_at

### `PhraseProgress` (kullanıcının o phrase ile ilişkisi — ileride spaced repetition için de temel olacak)
- id
- user_id (FK)
- phrase_id (FK)
- status (enum: `learning` / `learned`)
- swipe_left_count (int, kaç kere "bilmiyorum" denildi)
- swipe_right_count (int, kaç kere "biliyorum" denildi)
- last_reviewed_at
- next_review_at (nullable, ileri faz için spaced repetition)

---

## 6. Swipe / Tekrar Mekanizması (Prototip için basit versiyon)

- Kullanıcının önünde bir **kuyruk (queue)** var: önce `status = learning` olan phrase'ler, sonra hiç görülmemişler.
- **Sağa kaydırma (öğrendim):** `status = learned` yapılır, kuyruktan çıkar (ana döngüden düşer). İleride (spaced repetition fazında) belirli aralıklarla tekrar gösterilebilir.
- **Sola kaydırma (öğrenemedim):** `status = learning` kalır, kartın kuyruktaki sırası korunur/öne alınır — yani kullanıcı öğrenene kadar bu kart tekrar tekrar karşısına çıkmaya devam eder. Basit yaklaşım: sola kaydırılan kart, kuyruğun sonuna değil, yakın bir sıraya (örn. 3-5 kart sonrasına) tekrar eklenir ki art arda hep aynı kartı görmesin ama sık karşılaşsın.
- Bu mekanizma prototipte basit tutulacak; gerçek spaced repetition (Leitner sistemi, SM-2 algoritması vb.) ileri bir fazda eklenecek (bkz. Faz 6).

---

## 7. AI Destekli Otomatik Phrase Üretimi

Kullanıcı sadece İngilizce öğrenmek istediği bir cümle/deyim/atasözü girdiğinde, arka planda bir LLM API çağrısı ile:
1. Cümleyi anlamlı kelime/hece parçalarına ayırır,
2. Her parçaya kullanıcının ana diline (örn. Türkçe) yakın sesteş bir karşılık bulur,
3. Bu sesteş karşılıkları birbirine bağlayan kısa, akılda kalıcı, mizahi bir görsel hikaye üretir,
4. Sonucu yukarıdaki `word_breakdown` (sıralı array) formatında JSON olarak döner.

Kullanıcı bu otomatik üretilen sonucu **inceleyip onaylayabilir veya elle düzenleyebilir**, sonra kaydeder. Prompt tasarımı Faz 4'te detaylandırılacak; model olarak Anthropic Claude API kullanılması önerilir (Claude Code zaten Anthropic ekosisteminde olduğu için API key yönetimi kolaylaşır), ama OpenAI API de alternatif olarak bırakılabilir.

---

## 8. Arayüz (UI/UX) Yönergeleri

- **Hedef kitle:** Genç kullanıcılar.
- **Genel his:** Açık (light) arka plan, üzerine canlı/parlak renklerle vurgulanmış ama koyu tonlarla dengelenmiş temiz bir tasarım (örn. beyaz/krem arka plan + canlı mor/turuncu/yeşil aksan renkleri + koyu gri/siyah metin tonları).
- **Kart arayüzü (swipe):** Tinder benzeri kart yığını — büyük, okunaklı kartlar, yumuşak gölgeler, kaydırma animasyonları.
- **Tipografi:** Modern, yuvarlak hatlı, okunaklı bir font (örn. Google Fonts üzerinden Poppins, Inter, Nunito gibi).
- **Mobil uyumluluk:** Uygulama büyük olasılıkla telefonlarda kullanılacak, bu yüzden responsive/mobile-first tasarım şart.
- Karmaşık animasyon kütüphaneleri yerine saf CSS transition/transform ile swipe efekti yeterli (prototip aşamasında).

---

## 9. Fazlara Bölünmüş Yol Haritası

Aşağıdaki fazları Claude Code'a **ayrı ayrı, birer birer** ver. Her faz bir öncekinin üzerine inşa edilir.

### Faz 0 — Proje İskeleti ve Altyapı Kurulumu
- Django projesi oluşturma, temel app yapısı (`users`, `phrases` gibi).
- Supabase projesi bağlantısı (PostgreSQL connection string, `.env` yönetimi).
- Statik dosyalar (HTML/CSS/JS) için Django'nun static/templates yapısının kurulması.
- Vercel deployment için gerekli yapılandırma dosyaları (`vercel.json`, `requirements.txt`, WSGI/ASGI ayarları).
- Git repo yapısı ve `.gitignore`.

### Faz 1 — Kullanıcı Kayıt / Giriş Sistemi
- E-posta + parola ile kayıt ve giriş ekranları (HTML/CSS/JS + Django view'ları).
- Supabase Auth kullanımı ya da Django'nun kendi auth sistemi + Supabase'i sadece veritabanı olarak kullanma kararının netleştirilmesi (öneri: prototipte basitlik için Django'nun kendi `auth` sistemi + Supabase Postgres DB kullanılabilir; Supabase Auth entegrasyonu daha fazla ek iş gerektirir).
- Oturum yönetimi (login required sayfalar).
- Basit, temiz bir kayıt/giriş arayüzü (Bölüm 8'deki tasarım diliyle uyumlu).

### Faz 2 — Phrase Veri Modeli ve Manuel Ekleme
- `Phrase` ve `PhraseProgress` modellerinin Django ORM ile tanımlanması, migration.
- "+ Ekle" ekranı: kullanıcının orijinal cümle, çeviri, kelime kelime ses karşılıkları (dinamik olarak kelime sayısı kadar input alanı) ve hikaye girebileceği form.
- Girilen `word_breakdown` sırasının korunduğundan emin olunması (Bölüm 2'deki kritik kural).
- Kaydetme, listeleme, silme, düzenleme (CRUD) işlevleri.

### Faz 3 — Ana Ekran: Kart Yığını ve Swipe Mekanizması
- Kullanıcının phrase havuzunu kart yığını olarak gösteren ana ekran.
- Her kartta Abstract / Image (sıralı kelime-ses eşleşmesi) / Association bilgisinin düzenli gösterimi.
- Sağa/sola swipe (dokunmatik + mouse ile sürükleme, ayrıca buton alternatifi de olmalı — erişilebilirlik için).
- Swipe sonrası `PhraseProgress` güncellemesi ve Bölüm 6'daki basit tekrar mantığının uygulanması.

### Faz 4 — AI Destekli Otomatik Phrase Üretimi
- LLM API entegrasyonu (Claude API veya OpenAI API), `.env` üzerinden API key yönetimi.
- Kullanıcının sadece hedef cümleyi girdiği, sistemin geri kalanını (word_breakdown + association_story) ürettiği akış.
- Üretilen sonucun önizleme/düzenleme ekranı, onaylanınca kaydetme.
- Prompt şablonunun Bölüm 2 ve 7'deki formatla birebir uyumlu JSON döndürecek şekilde tasarlanması.

### Faz 5 — Arayüz Cilası (UI/UX Polish)
- Bölüm 8'deki tasarım dilinin tüm ekranlara tutarlı şekilde uygulanması.
- Renk paleti, tipografi, ikonografi netleştirilmesi.
- Mobil responsive testler ve düzeltmeler.
- Boş durum (empty state), yüklenme (loading), hata mesajları gibi UX detayları.

### Faz 6 — Deployment ve İyileştirmeler
- Vercel'e canlı deployment, environment variable yönetimi (Supabase keys, LLM API key).
- Temel istatistik ekranı (kaç phrase öğrenildi, kaç tanesi öğrenme aşamasında).
- (Opsiyonel, ileri faz) Gerçek spaced repetition algoritması (Leitner/SM-2).
- (Opsiyonel, ileri faz) Sesli okuma (text-to-speech) desteği.
- (Opsiyonel, ileri faz) Farklı hedef dillere genişletme.

---

## 10. Claude Code'a Fazları Verirken Kullanılacak Prompt Şablonu

Her faza başlarken Claude Code'a şu formatta bir mesaj verilebilir:

```
Bu proje "PhrasePhrase" adlı bir dil öğrenme uygulaması. Proje detaylarını
phrasephrase-proje-plani.md dosyasında bulabilirsin, lütfen önce onu oku.

Şu an [FAZ X - FAZ ADI] üzerinde çalışmak istiyorum. Bu fazda şunları
yapmanı istiyorum: [ilgili faz maddelerini yapıştır].

Önceki fazlarda şunlar tamamlandı: [varsa özetle].

Lütfen adım adım ilerle, her önemli adımdan sonra bana durumu özetle.
```

Bu sayede Claude Code her seferinde tüm proje bağlamını (`phrasephrase-proje-plani.md` dosyası üzerinden) görebilir ama sadece o anki fazın kapsamında çalışır.

---

## 11. Açık Kalan Kararlar (İleride Netleştirilecek)

- Supabase Auth mu, yoksa Django auth + Supabase sadece DB mi kullanılacak? (Faz 1'de karar verilecek, prototip için Django auth önerilir.)
- AI sağlayıcısı: Claude API mi, OpenAI API mi? (Faz 4'te karar verilecek.)
- Kelime bazlı ses karşılığı üretimi tamamen AI'ya mı bırakılacak, yoksa kullanıcıya öneri + düzenleme imkanı mı sunulacak? (Öneri: ikisi de — AI üretir, kullanıcı düzenler.)
