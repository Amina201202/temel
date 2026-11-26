# Təməl — Sənin bilik radarın

> Şagird səhv edəndə səbəb çox vaxt həmin mövzuda deyil, **əvvəlki siniflərdə qalan boşluqdadır**.
> Təməl adaptiv diaqnostik testdir: səhv cavabdan sonra mövzular qrafı üzrə geriyə enir və **kök səbəbi** tapır.

LTC Lab AI Engineering kursunun 6 aylıq final layihəsi · Müəllif: **Amina** ([@Amina201202](https://github.com/Amina201202))

<!-- TODO: ekran görüntüləri (şagird xəritəsi, müəllim radarı, Telegram) -->

---

## Problem

Adi test yalnız "səhvdir" deyir. Məsələn, 9-cu sinif şagirdi kvadratik funksiyada səhv edir, amma əsl səbəb **6-cı sinifdə** öyrənmədiyi əməllər ardıcıllığıdır. Müəllimin 25 şagirdin hər birinin boşluğunu əl ilə axtarmağa vaxtı yoxdur.

## Həll

1. **Adaptiv test (LangGraph agenti):** səhv cavabdan sonra əvvəlki mövzulara, lazım olsa əvvəlki siniflərə enir. 5–12 sualda kök səbəbi tapır.
2. **Bilik xəritəsi:** kök səbəb, zəif, bilir, "yəqin bilir", yoxlanmadı.
3. **Şəxsi izah (RAG):** dərslikdən, mənbə səhifəsi ilə; **səsli** dinləmək də olur (TTS).
4. **3 günlük plan** + **Telegram xatırlatmaları** (n8n).
5. **Müəllim:** canlı **Sinif radarı**, bütün siniflər üzrə ümumi baxış, Excel ixracı, **həftəlik Telegram hesabatı**.
6. **Telefona tətbiq kimi quraşdırılır** (PWA).

Əhatə: riyaziyyat, **5–9-cu siniflər**, 9 dərslik bölməsi, ~115 mövzu, ~350 yoxlanmış sual şablonu.

---

## Arxitektura

```
 Şagird (PWA)   Müəllim paneli   Admin (Streamlit)        Telegram
      │               │                 │                    │
      └───────────────┴────────┬────────┘                    │
                               ▼                             ▼
                         FastAPI (API) ◄──── webhook ──── n8n (Wait, Schedule)
     ┌───────────┬─────────────┼──────────────┬──────────────┐
     ▼           ▼             ▼              ▼              ▼
 LangGraph   RAG (pgvector)  Guardrails   Klassik ML     Gemini 2.5 Flash
 diaqnoz     dərslik         + lokal      (Random        (OCR, generasiya,
 agenti      səhifələri      fine-tuned   Forest)        izah, TTS)
 (Postgres                   model
 checkpoint)                 (Ollama)
     └───────────── PostgreSQL + pgvector · Redis ─────────────┘
```

| Qat | Texnologiya |
|---|---|
| Backend | FastAPI, Pydantic, SQLAlchemy 2.1, PostgreSQL + pgvector, Redis |
| LLM | Google Gemini 2.5 Flash (structured output), `gemini-embedding-001`, Gemini TTS |
| Agent | LangGraph (StateGraph, interrupt / HITL, PostgresSaver checkpoint) |
| Klassik ML | scikit-learn (Random Forest) |
| Fine-tuning | MLX + mlx-lm (QLoRA), Llama 3.2 1B, Ollama |
| Avtomatlaşdırma | n8n, Telegram Bot API |
| UI | HTML/CSS/JS (PWA), Streamlit (admin), ağ/qaranlıq tema |
| Infra | Docker Compose, ngrok (demo), Caddy (prod) |

---

## Necə işləyir

### 1. Dərslikdən bilik qrafı
PDF bölmə yüklənir, Gemini OCR edir, mövzuları və aralarındakı asılılıqları çıxarır. **Siniflərarası əlaqələr** üçün AI hər mövzuya əvvəlki siniflərdən prerekvizit təklif edir və 1–5 bal verir. Kod yalnız ≥4 balı saxlayır, dolayı əlaqələri atır (transitive reduction), sonra insan təsdiqləyir.

> İlk versiyada AI ad oxşarlığına aldanırdı (5 əlaqədən 5-i səhv idi). Bal sistemi və süzgəcdən sonra 8-ci sinifdə **17 əlaqənin hamısı düzgün** çıxdı.

### 2. Sual bankı: AI yazır → kod yoxlayır → AI düzəldir
AI sual **şablonu** yazır: dəyişənlər, şərtlər, düz cavab, 3 səhv variant və hər səhvin hansı yanlış anlayışı göstərdiyi. Kod şablonu **30 dəfə** işlədir, problem varsa AI-a bir dəfə düzəltdirir, sonda admin təsdiqləyir (HITL).
Riyazi ifadələr **öz AST kalkulyatorumuzla** hesablanır (`eval` yoxdur). Ona görə prompt injection kod icra edə bilmir.

### 3. Adaptiv diaqnoz (LangGraph)
`plan → pick → ask (interrupt) → grade → diagnose`. Səhv cavabdan sonra prerekvizitlərə enir. Bir dəfə səhv edəndə ikinci sual verilir (slip tolerance), çətin suala düz cavab verilibsə, əvvəlki mövzular "yəqin bilir" sayılır.

### 4. Guardrails ("Sualın var?" və Telegram botu)
Giriş: uzunluq → şəxsi məlumat (AZ telefon, e-poçt) → injection (AZ/EN/RU) → **mövzu yoxlaması**.
Çıxış: dərsliyə əsaslanma (grounding), PII, uzunluq. Redis rate limit: 5 sual.

### 5. Klassik ML: təsadüfi basma detektoru
Real pilotda bir şagird 12 sualı **36 saniyəyə** basdı və onun "kök səbəbləri" müəllimi yanlış yönləndirirdi.
- Sintetik şagird simulyatoru: normal, zəif, **"dahi"** (tez və düz), təsadüfi, yarıda bezən
- 9 xüsusiyyət: vaxt paylanması, düzgünlük, asan suallarda düzgünlük, sürətlənmə
- **Random Forest F1 0.92** (köhnə "1 dəqiqədən tez" qaydası: 0.68). Real testlərdə 14/14 düzgün.
- Belə testlər müəllim radarında ⚠️ ilə işarələnir və statistikaya düşmür.

### 6. Fine-tuning: lokal guard modeli
Mövzu yoxlaması hər sualda Gemini-yə gedirdi. **Distillation** etdik: Gemini 1.404 nümunə yazıb etiketlədi, kiçik **Llama 3.2 1B** modeli **QLoRA** ilə (MLX, MacBook M3) bunlardan öyrəndi. Öyrədilən parametrlər cəmi **0.23%** idi.

| | Baza model | Fine-tuned |
|---|---|---|
| Test (görmədiyi mövzular, Gemini ilə uyğunluq) | 0% (formatı belə izləmir) | **85.6%** |
| Red team (insan etiketi, mövzu sualları) | 0/15 | **14/15** |

Öyrənmə iki mərhələdə getdi: 300 iter (lr 1e-4) + 300 iter (lr 5e-5), val loss **13.07 → 0.10**.
Model **Ollama**-da işləyir (safetensors → `ollama create`), API ona OpenAI-uyğun endpoint ilə müraciət edir.

**Tam guardrails red team-i (24 hücum + real sual): Gemini vs lokal model**

| | Gemini 2.5 Flash | **Fine-tuned Llama 1B (Ollama)** |
|---|---|---|
| Düzgün | 24/24 | **23/24** |
| Real şagird sualı buraxıldı | 8/8 | **8/8** |
| Sürət | ~460 ms/sual | **67 ms/sual** |
| Xərc / internet | pullu, internet lazım | **$0, internetsiz** |

Sistem **hibriddir**: Ollama varsa mövzu yoxlaması lokal işləyir, yoxdursa avtomatik Gemini-yə keçir.

### 7. n8n + Telegram
**API qərar verir, n8n gözləyir və göndərir.**
- Şagird: 3 günlük plan hər gün Telegram-a gəlir. Bota sual yazanda guardrails və RAG ilə cavab alır.
- Müəllim: hər bazar ertəsi saat 9:00-da həftəlik hesabat (kök səbəblər, siniflər, tövsiyə).

---

## Qiymətləndirmə

| Nə | Necə | Nəticə |
|---|---|---|
| Kök səbəb dəqiqliyi | sintetik şagirdlər (səhv/təxmin səs-küyü ilə) | səs-küysüz **99%**, orta **80%**, yüksək **60%**; sabit test **22–47%** |
| Sual sayı | adaptiv vs sabit test | **~10** vs 13.9 |
| İzah keyfiyyəti | LLM-as-Judge vs insan reytinqi | razılaşma **15/15**, aydınlıq ±1 daxilində **14/15** |
| Guardrails | 24 maddəlik red team | **24/24** |
| Təsadüfi basma (ML) | sintetik + 14 real test | **F1 0.92**, real 14/14 |
| Fine-tuned guard | test + tam red team | **85.6%**; red team **23/24** (Gemini 24/24), **67 ms** vs 460 ms |

### Real istifadəçilər
9-cu sinif şagirdləri sınadı. Bir şagirdin səhvləri 9-cu sinif mövzusunda idi, Təməl isə səbəbi **6-cı sinfin "Əməllər ardıcıllığı"** mövzusunda tapdı.

> *"Birhədliləri açdım, sən demə heç nə bilmirmişəm, axırda izah da eləyir. Bunu təqdim eləsən də, eləməsən də mən işlədəcəm şəxsən."* — 9-cu sinif şagirdi

Rəylərdən sonra edilən düzəlişlər: riyazi yazılış sadələşdirildi (`^`, `*` əvəzinə `x²`), "kağız-qələm hazırla" ipucu əlavə olundu, təsadüfi basma detektoru yarandı.

---

## İşə salmaq

```bash
cp .env.example .env        # GEMINI_API_KEY, POSTGRES_PASSWORD, ADMIN_PASSWORD, TELEGRAM_*
docker compose up -d --build
```

| | Ünvan |
|---|---|
| Şagird | http://localhost:8010/app/ |
| Müəllim | http://localhost:8010/app/teacher.html |
| Admin | http://localhost:8510 |
| n8n | http://localhost:5679 (`n8n/workflows/*.json` import) |

Əlavə:
```bash
docker compose exec api python -m app.careless          # ML modelini öyrət
docker compose exec api python -m app.evaluate guard     # red team
docker compose exec api python -m app.ft_data            # fine-tuning dataset
# Mac (MLX):
mlx_lm.lora --model mlx-community/Llama-3.2-1B-Instruct-4bit --train --data data/eval/ft --adapter-path ft/adapters --iters 300 --batch-size 8 --num-layers 8 --mask-prompt
python ft/eval_local.py --adapter ft/adapters
mlx_lm.fuse --model mlx-community/Llama-3.2-1B-Instruct-4bit --adapter-path ft/adapters2 --save-path ft/models/temel-guard-hf --dequantize
cd ft && ollama create temel-guard -f Modelfile
# .env: LOCAL_GUARD_URL=http://host.docker.internal:11434/v1/chat/completions
```

## Təhlükəsizlik
- Admin endpoint-ləri `X-Admin-Key` tələb edir; müəllim şifrələri scrypt hash ilə saxlanılır
- Riyazi ifadələr üçün `eval` istifadə olunmur, yalnız icazə verilmiş AST node-ları qəbul edilir
- Telegram webhook gizli açarla yoxlanılır; `/start` kodları birdəfəlikdir
- Real ad saxlanılmır (ləqəb), şəxsi məlumat bloklanır

## Gələcək iş
- Şəkilli həndəsə (şəkil koddan çəkilir, AI yalnız növünü seçir)
- Şagird hesabları: boşluğun zamanla bağlanmasını izləmək
- Digər fənlər, Play Store
- Məktəblərdə real istifadə

---
*LTC Lab · AI Engineering · 2026*
