# UPPETIT Neurobot

Корпоративная база знаний UPPETIT. PWA-приложение с RAG-пайплайном: отвечает на вопросы сотрудников строго по базе знаний. Не использует интернет, не додумывает, не галлюцинирует.

---

## Стек

| Слой | Технология |
|---|---|
| Backend | FastAPI + SQLAlchemy async + PostgreSQL + Redis |
| Frontend | React 18 + Vite + PWA (Workbox) |
| LLM | OpenAI gpt-4o-mini |
| Embeddings | text-embedding-3-small |
| Vector DB | FAISS (IndexFlatIP) |
| Парсинг KB | python-docx, pdfplumber, openpyxl |
| Auth | JWT (httpOnly cookies) + bcrypt + RBAC |
| Deploy | rsync + systemd |

---

## Структура проекта

```
UPPETIT_Neurobot/
├── backend/
│   ├── main.py              # FastAPI entry point, lifespan, SPA serving
│   ├── config.py            # Pydantic settings (.env)
│   ├── database.py          # Async SQLAlchemy engine
│   ├── models/              # SQLAlchemy models (User, Role, Chat, Message)
│   ├── core/
│   │   ├── auth.py          # JWT + bcrypt
│   │   ├── rbac.py          # Roles & permissions
│   │   └── limiter.py       # Rate limiting (slowapi + Redis)
│   ├── api/
│   │   ├── auth.py          # Login, refresh, logout, change-password
│   │   ├── chats.py         # CRUD чатов
│   │   ├── messages.py      # Сообщения + RAG-ответы
│   │   └── admin/
│   │       ├── users.py     # Управление пользователями
│   │       └── kb.py        # База знаний: статус, обновление, бенчмарк
│   ├── rag/
│   │   ├── rag_answerer.py  # RAG pipeline: поиск → GPT → ответ
│   │   ├── vector_store.py  # FAISS: build / search / persist
│   │   ├── chunker.py       # Разбивка на чанки с overlap
│   │   ├── kb_loader.py     # Парсинг docx/pdf/xlsx
│   │   └── gdrive.py        # Синхронизация с Google Drive
│   ├── benchmark.py         # Автоматический бенчмарк качества RAG
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx          # React Router, guards
│   │   ├── pages/           # ChatPage, Login, ChangePassword, Admin*
│   │   ├── components/      # Layout, ChatSidebar, ChatMessage, etc.
│   │   ├── api/             # Axios client + interceptors
│   │   └── store/           # Zustand (auth)
│   ├── public/              # Icons, fonts
│   └── vite.config.js       # PWA, proxy, version injection
└── deploy/
    ├── deploy.sh            # Деплой на staging/prod
    └── systemd/             # Service files
```

---

## Окружения

| | Staging | Production |
|---|---|---|
| URL | https://test.uppetitgpt.ru | https://uppetitgpt.ru |
| Порт | 8002 | 8001 |
| Путь | /opt/neurobot-staging | /opt/neurobot |
| Сервис | neurobot-staging | neurobot |

---

## Локальная разработка

### Backend

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.staging.example .env   # заполнить секреты
uvicorn main:app --reload --port 8001
```

### Frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173, proxy /api → localhost:8001
```

---

## Деплой

```bash
./deploy/deploy.sh staging           # backend + frontend на staging
./deploy/deploy.sh staging backend   # только backend
./deploy/deploy.sh staging frontend  # только frontend
./deploy/deploy.sh prod              # production
```

Скрипт автоматически: генерирует VERSION (git hash + dirty flag + timestamp), собирает frontend, синхронизирует через rsync, перезапускает сервис.

Пароль сервера читается из `~/.neurobot-deploy` (формат: `SERVER_PASS=...`).

---

## RAG-пайплайн

```
Google Drive (docx/pdf/xlsx)
        ↓
  kb_loader: парсинг → DocSection[]
        ↓
  chunker: разбивка (800 символов, overlap 150)
        ↓
  vector_store: embedding → FAISS IndexFlatIP
        ↓
  Вопрос пользователя → embedding → гибридный поиск
  (semantic + keyword bonus, diversity filter)
        ↓
  GPT-4o-mini (temperature=0.05, антигаллюцинационный промпт)
        ↓
  Ответ + источники + изображения
```

---

## Роли и доступ

| Роль | Права |
|---|---|
| employee | chat:use |
| admin | chat:use, kb:manage, user:manage, admin:panel |

---

## Настройка параметров RAG

В `.env`:

```
CHUNK_SIZE=800
CHUNK_OVERLAP=150
TOP_K=6
MIN_SCORE=0.20
MIN_SEMANTIC_SCORE=0.20
CHAT_MODEL=gpt-4o-mini
MAX_TOKENS=1500
```
