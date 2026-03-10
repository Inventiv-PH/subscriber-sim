# Subscriber Sim: System Architecture

A LoRA fine-tuning pipeline that trains a Jasmin chatbot to respond authentically as a content creator interacting with subscriber archetypes. The system combines data collection, model training, and interactive inference.

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Subscriber Sim Pipeline                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────────┐      ┌─────────────────┐                 │
│  │  Data Collection │ ────▶│  Training Data  │                 │
│  │   (Gradio UI)    │      │  (sessions.jsonl)                 │
│  └──────────────────┘      └─────────────────┘                 │
│                                     │                            │
│                                     ▼                            │
│                            ┌─────────────────┐                  │
│                            │  Fine-Tuning    │                  │
│                            │  (LoRA Adapter) │                  │
│                            └─────────────────┘                  │
│                                     │                            │
│           ┌─────────────────────────┴──────────────────────┐   │
│           ▼                                                  ▼   │
│  ┌──────────────────┐                          ┌──────────────┐ │
│  │   PEFT Adapter   │                          │   MLX Adapter│ │
│  │ (HuggingFace)    │                          │ (Optimized)  │ │
│  └──────────────────┘                          └──────────────┘ │
│           │                                             │        │
│           └─────────────────────┬─────────────────────┘         │
│                                  ▼                               │
│                    ┌──────────────────────────┐                 │
│                    │  Inference Server        │                 │
│                    │  (MLX or Modal GPU)      │                 │
│                    └──────────────────────────┘                 │
│                                  │                               │
│                                  ▼                               │
│                    ┌──────────────────────────┐                 │
│                    │  Streamlit Chat UI       │                 │
│                    │  (Interactive Simulator) │                 │
│                    └──────────────────────────┘                 │
│                                  │                               │
│                                  ▼                               │
│                    ┌──────────────────────────┐                 │
│                    │  SQLite Chat Database    │                 │
│                    │  (Conversation History)  │                 │
│                    └──────────────────────────┘                 │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Core Components

### 2.1 Application Layer (`app/`)

The Streamlit-based web UI and supporting modules.

#### **main.py**
- **Purpose**: Streamlit entry point for the interactive chat UI
- **Features**:
  - Subscriber archetype selection interface
  - Real-time chat with the fine-tuned model
  - Conversation management (create, view, delete)
  - Session persistence to SQLite database
  - Custom CSS styling and UI enhancements
- **Architecture**:
  - Sidebar for navigation and conversation history
  - Main chat panel with message display and input
  - Archetype picker cards with descriptions and emoji
- **Workflows**:
  - **Training Mode**: User types as Jasmin, model responds as subscriber archetype → data collection
  - **Inference Mode**: Model responds as Jasmin to real subscriber inputs

#### **archetypes.py**
- **Purpose**: Define 7 subscriber persona archetypes
- **Archetypes**:
  1. **Horny** (🔥): Sexually forward, asks for explicit content
  2. **Cheapskate** (💸): Cost-conscious, negotiates discounts
  3. **Casual** (💬): Seeks genuine conversation and connection
  4. **Troll** (😈): Antagonistic, tests boundaries
  5. **Whale** (💰): High-value spender, supportive
  6. **Cold** (❄️): Detached, hesitant engagement
  7. **Simp** (😍): Devoted, seeks emotional connection
- **Structure**:
  - `ARCHETYPES` dict: label, emoji, icon, gradient, description, opener message, intro message
  - `_SUBSCRIBER_SYSTEMS`: System prompt templates for each archetype
  - `get_archetype_mid_convo_reminder()`: In-conversation nudges to maintain character consistency
- **Usage**: Loaded by `main.py` for UI rendering and by `inference.py` for generation parameters

#### **inference.py**
- **Purpose**: Query the fine-tuned model and stream responses
- **Key Functions**:
  - `query_model(conversation_history, archetype) → Generator[str]`: Stream model responses
  - `format_conversation_for_prompt()`: Convert message history to prompt format
- **Inference Backends**:
  - **Modal GPU**: Cloud-hosted inference via Modal (primary in production)
  - **MLX Local**: Local inference server on `localhost:8080` (fallback/testing)
- **Generation Parameters**:
  - Default: `max_tokens=100, temperature=0.75, top_p=0.85`
  - Per-archetype tuning for consistency (e.g., troll: `temp=0.80`, casual: `temp=0.65`)
  - Stop tokens: `\n\nJasmin:`, `\n\nUser:`, `\n\n[`
- **Error Handling**: Graceful fallback if backend unavailable

#### **database.py**
- **Purpose**: SQLite persistence layer with thread-safe operations
- **Schema**:
  - `conversations`: id (TEXT PK), title, archetype, created_at, updated_at
  - `messages`: id (INT AI PK), conversation_id (FK), role, content, created_at
- **Key Functions**:
  - `init_db()`: Create tables and indexes
  - `create_conversation(title, archetype) → str`: Return conversation UUID
  - `save_message(conversation_id, role, content)`: Insert or update message
  - `get_conversations() → List[Row]`: Retrieve all conversations
  - `delete_conversation(conversation_id)`: Cascade delete with FK
- **Features**:
  - Thread-safe with `threading.Lock()` for concurrent access
  - WAL (Write-Ahead Logging) mode for better concurrency
  - Foreign key constraints enabled
  - Persistent storage at `data/chat.db` (configurable via `DB_PATH` env var)

---

### 2.2 Data & Training

#### **data/sessions.jsonl**
- **Format**: One JSON object per line (JSONL)
- **Volume**: 256 pre-parsed sessions, 8,496 conversation turns
- **Source**: Real OnlyFans chat exports (anonymized)
- **Structure** (single turn):
  ```json
  {
    "text": "<s>[INST] <<SYS>>\n{system_prompt}\n<</SYS>>\n\n{user_message}[/INST] {assistant_response}</s>"
  }
  ```
- **Role Mapping** (important!):
  - In Gradio UI: User (you) = Jasmin, Assistant = Subscriber
  - In JSONL training data: Roles are **flipped**
    - `[INST]` block (user token) = Subscriber message
    - Response block (assistant token) = Jasmin response
  - This ensures the model learns to respond *as Jasmin*

#### **scripts/parse_chats.py**
- **Purpose**: Parse raw OnlyFans chat exports → `data/sessions.jsonl`
- **Input**: Raw chat export files in `chat data/` directory
- **Processing**:
  - Reads chat history from each file
  - Groups consecutive subscriber/creator messages into turns
  - Formats as Llama 2 Chat instruction format
  - Deduplicates messages
  - Filters invalid/incomplete turns
- **Output**: Single unified `sessions.jsonl` file
- **Logging**: Detailed audit of all processing steps to console/logs

#### **scripts/convert_adapter_to_mlx.py**
- **Purpose**: Convert PEFT LoRA adapter → MLX-optimized format
- **Input**: `models/finetuned/` (HuggingFace PEFT adapter)
- **Process**:
  1. Load base Llama 3.1 8B model config
  2. Convert SafeTensors weights to MLX format
  3. Merge adapter architecture into MLX config
  4. Save to `models/finetuned-mlx/`
- **Output**: MLX-compatible adapter + model config for local inference
- **Optimization**: Reduces model size and improves inference speed on Apple Silicon

#### **scripts/audit_data.py**
- **Purpose**: Validate training data integrity
- **Checks**:
  - Message count and unique contributors
  - Turn length distribution
  - Coverage of archetype examples
  - Format compliance (Llama 2 Chat structure)
  - Duplicate detection
- **Output**: Summary statistics and warnings for malformed data

#### **scripts/modal_server.py**
- **Purpose**: Cloud-hosted inference endpoint on Modal GPU
- **Deployment**: `make modal-deploy`
- **Features**:
  - Auto-scales GPU containers based on demand
  - Serves `/infer` endpoint for chat queries
  - Handles LoRA adapter loading and merging
  - Production-grade logging and error handling
- **Setup**: Requires Modal account + token (`MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`)

---

### 2.3 Model Artifacts

#### **models/adapter/**
- PEFT (Parameter-Efficient Fine-Tuning) adapter components
- Source format for training
- Not directly used for inference; converted to MLX format

#### **models/finetuned/**
- HuggingFace PEFT adapter from fine-tuning job
- Contains:
  - `adapter_model.safetensors`: Weight deltas (LoRA)
  - `adapter_config.json`: LoRA configuration (rank, alpha, target modules)
  - Merges with Llama 3.1 8B base during inference

#### **models/finetuned-mlx/**
- MLX-optimized adapter for local inference
- Generated by `scripts/convert_adapter_to_mlx.py`
- Used by `start_mlx_server.sh` for local deployment
- Significantly faster inference on Mac/Metal

---

### 2.4 Deployment & Infrastructure

#### **Docker & Docker Compose**

**docker-compose.yml**:
- Service: `chat` (Streamlit app)
- Mounts: `./data/` ↔ `/app/data` (persistent SQLite DB)
- Environment Variables:
  - `INFERENCE_BACKEND`: `modal` (GPU) or `mlx` (local)
  - `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`: Modal authentication
  - `MLX_SERVER_URL`: Local MLX server address (for fallback)
  - `MODEL_NAME`: Llama 3.1 8B (4-bit quantized)
  - `DB_PATH`: SQLite database path (default: `/app/data/chat.db`)
- Networking: Port 8501 (Streamlit)

**Dockerfile**:
- Base: `python:3.12-slim`
- Installs: `app_requirements.txt` (Streamlit, requests, etc.)
- Entrypoint: `streamlit run app/main.py`
- Health: Configurable restart policy

#### **Makefile Workflows**

```
Setup Phase:
  make setup       → Create venv, install mlx-lm + Streamlit deps
  make convert     → Convert PEFT adapter → MLX format

Run Locally (2-terminal):
  Terminal 1: make server    → Start MLX inference on localhost:8080
  Terminal 2: make app       → Start Streamlit on localhost:8501
  Terminal 2: docker-compose up  → Run app in Docker (needs MLX server in Terminal 1)

Cloud Deployment:
  make modal-setup   → Install + authenticate Modal
  make modal-deploy  → Deploy inference to Modal GPU
  make modal-serve   → Run Modal server locally for testing
  make hf-deploy     → Push to HuggingFace Spaces

Data Processing:
  make parse         → Parse raw chats → sessions.jsonl

Cleanup:
  make clean         → Remove MLX cache + DB
  make clean-all     → Remove venv + generated files
```

---

## 3. Data Flow

### 3.1 Training Pipeline (Google Colab)

```
Raw Chat Exports (OnlyFans)
         │
         ▼
   parse_chats.py
         │
         ▼
data/sessions.jsonl (256 sessions, 8,496 turns)
         │
         ├─────────┐
         │         │
    Notebook    Notebook
    Cell 7:     Cell 2-4:
    Format      Subscriber
    Training    Bots
    Data        │
         │      └──────────┐
         │                 │
         ▼                 ▼
    SFTTrainer (trl)   Gradio UI
         │          (data collection)
         │                 │
         │        Google Drive
         │        (additional
         │         sessions)
         │                 │
         └────────┬────────┘
                  ▼
         Unified Training Data
                  │
                  ▼
    Fine-tuning (3 epochs, LoRA rank=16)
                  │
                  ▼
    models/finetuned/ (PEFT adapter)
                  │
                  ▼
    Test inference (Cell 9)
```

### 3.2 Inference & Serving

```
Fine-tuned Adapter
         │
         └────────────┬────────────┐
                      │            │
                  PEFT Format   Convert to MLX
                      │            │
         Modal GPU    │    Local MLX Server
         Inference    │    (Apple Silicon)
                      │            │
                      ▼            ▼
                  Inference Backends
                      │            │
                      └────┬───────┘
                           │
                           ▼
                    Streamlit Chat UI
                           │
                    ┌──────┴──────┐
                    │             │
                User Messages   Assistant
                (Jasmin)        Responses
                    │            (Archetype)
                    │             │
                    └──────┬──────┘
                           ▼
                    SQLite Persistence
                    (data/chat.db)
```

### 3.3 Conversation Lifecycle

```
1. User selects archetype (e.g., "horny")
   │
   ▼
2. System initializes conversation
   - Creates conversation record in SQLite
   - Loads archetype system prompt + generation parameters
   │
   ▼
3. User types as Jasmin
   │
   ▼
4. App queries inference backend with:
   - Conversation history
   - Archetype system prompt
   - Archetype-specific generation parameters
   │
   ▼
5. Model streams response (subscriber replies to Jasmin)
   │
   ▼
6. Response saved to SQLite
   │
   ▼
7. Display in chat UI
   │
   ▼
8. Repeat steps 3-7 until conversation ends
   │
   ▼
9. Optional: Export to training data (during development)
```

---

## 4. Key Technologies

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Base Model** | Llama 3.1 | 8B (4-bit quantized) | Fast, efficient instruction-following |
| **Fine-Tuning** | Unsloth + trl (SFTTrainer) | Latest | Memory-efficient LoRA training |
| **Adapter Framework** | PEFT | - | Parameter-efficient fine-tuning |
| **Inference (Local)** | MLX (MLX-LM) | Latest | Metal-optimized inference on Mac |
| **Inference (Cloud)** | Modal | - | Serverless GPU scaling |
| **Web UI** | Streamlit | 1.40+ | Interactive chat interface |
| **Database** | SQLite3 | Built-in | Lightweight persistence |
| **Containerization** | Docker + Compose | Latest | Reproducible deployments |
| **Environment Management** | Python venv | 3.12 | Isolated dependencies |

---

## 5. Configuration & Environment

### Environment Variables

```bash
# Inference Backend
INFERENCE_BACKEND=modal              # "modal" (GPU) or "mlx" (local)

# Modal Authentication (if using Modal)
MODAL_TOKEN_ID=<your-token-id>
MODAL_TOKEN_SECRET=<your-token-secret>

# MLX Server (if using local MLX)
MLX_SERVER_URL=http://localhost:8080
MODEL_NAME=mlx-community/Meta-Llama-3.1-8B-Instruct-4bit

# Database
DB_PATH=/app/data/chat.db

# Logging
DEBUG=false                          # Set to "true" for verbose logging
```

### Directory Structure

```
subscriber-sim/
├── app/
│   ├── main.py              # Streamlit UI entry point
│   ├── archetypes.py        # Subscriber persona definitions
│   ├── inference.py         # Model query interface
│   ├── database.py          # SQLite persistence layer
│   └── __pycache__/
├── models/
│   ├── adapter/             # Adapter config (reference)
│   ├── finetuned/           # PEFT adapter (HuggingFace format)
│   └── finetuned-mlx/       # MLX-optimized adapter
├── scripts/
│   ├── parse_chats.py       # Raw export → sessions.jsonl
│   ├── convert_adapter_to_mlx.py  # PEFT → MLX format
│   ├── audit_data.py        # Validate training data
│   └── modal_server.py      # Cloud inference endpoint
├── data/
│   ├── sessions.jsonl       # 256 pre-parsed training sessions
│   ├── chat data/           # Raw OnlyFans exports (source)
│   └── chat.db              # SQLite conversation DB (created at runtime)
├── chat data/               # Raw chat exports directory
├── Dockerfile               # Container specification
├── docker-compose.yml       # Multi-container orchestration
├── Makefile                 # Build & run recipes
├── requirements.txt         # MLX-LM + script dependencies
├── app_requirements.txt     # Streamlit + UI dependencies
├── start_mlx_server.sh      # MLX server launcher
├── subscriber_sim.ipynb     # Training notebook (Colab)
├── subscriber_sim_v2.ipynb  # Enhanced training notebook (Colab)
└── README.md                # Project overview
```

---

## 6. Workflows

### 6.1 Local Development Setup

```bash
# 1. Clone and setup
git clone <repo>
cd subscriber-sim
make setup

# 2. Terminal 1: Start MLX inference server
make server

# 3. Terminal 2: Start Streamlit app
make app

# 4. Open http://localhost:8501 in browser
```

### 6.2 Deploying to Cloud (Modal)

```bash
# 1. Setup Modal authentication
make modal-setup

# 2. Deploy inference to Modal GPU
make modal-deploy

# 3. Copy returned endpoint URL to docker-compose.yml
# Set: MLX_SERVER_URL=https://<your-modal-endpoint>

# 4. Run app (will query Modal instead of local server)
docker-compose up
```

### 6.3 Processing New Chat Data

```bash
# 1. Place raw chat exports in chat data/
ls chat\ data/

# 2. Parse to training format
make parse

# 3. Verify output
head -5 data/sessions.jsonl

# 4. Use in training (Colab notebook)
# Upload sessions.jsonl to Colab, fine-tune on updated data
```

### 6.4 Fine-Tuning (Google Colab)

See `subscriber_sim_v2.ipynb` for full workflow. Key steps:

```python
# Cell 0-4: Bootstrap + load model
# Cell 6: Setup LoRA adapter (rank=16, target q/k/v/o/gate/up/down)
# Cell 7: Load & format training data from sessions.jsonl
# Cell 8: Train with SFTTrainer (3 epochs, batch=2, lr=2e-4)
# Cell 9: Test inference
# Cell 10: Subscriber sim for additional data collection
```

---

## 7. Performance Characteristics

| Metric | Value | Notes |
|--------|-------|-------|
| **Model Size** | 8B parameters (4-bit) | ~3.5 GB VRAM |
| **Inference Latency** | 2-5 sec (MLX) / 1-3 sec (Modal GPU) | Depends on response length |
| **Training Time** | ~30 min (Colab A100) | 3 epochs on 8,496 turns |
| **LoRA Adapter Size** | ~50 MB | PEFT format |
| **Database I/O** | Sub-100ms per message | SQLite WAL mode |
| **Concurrent Users** | 1 (single instance) | Multi-instance via Docker |

---

## 8. Error Handling & Resilience

### Model Inference Failures

- **Backend Unavailable**: Falls back to generic error message in UI
- **Token Limit**: Truncates long conversations; prioritizes recent messages
- **Generation Timeout**: Cancels request after 30 sec; returns partial response
- **Logging**: All errors logged to stdout (visible in Docker logs)

### Database Failures

- **Corruption**: WAL mode prevents most corruption; manual recovery via `sqlite3 chat.db "PRAGMA integrity_check"`
- **Lock Timeout**: Thread-safe `_lock` with 5-sec timeout; retries on failure
- **Disk Full**: Graceful degradation; warns user, continues chatting

### Archetype Consistency

- **Mid-conversation Drift**: Periodic system prompt injections (`get_archetype_mid_convo_reminder()`)
- **Parameter Tuning**: Per-archetype generation parameters (temp, top_p, etc.)
- **Testing**: Manual testing in `subscriber_sim_v2.ipynb` Cell 9

---

## 9. Security Considerations

### Data Privacy

- Raw chat data is **anonymized** (names/identifiers removed)
- All conversations stored locally in `data/chat.db` (not synced to cloud)
- Modal GPU inference doesn't log conversation history
- `.gitignore` prevents accidental commits of sensitive data

### API Authentication

- **Modal**: Token-based auth via `.modal.toml` or env vars
- **MLX Server**: No auth (local network only)
- **Streamlit**: No built-in auth (assumes trusted environment)

### Model Safety

- Base model: Llama 3.1 (well-documented safety guardrails)
- Fine-tuning data: Curated real conversations (no synthetic harmful data)
- Generation: Conservative parameters (temp=0.65-0.80) prevent hallucination

---

## 10. Future Enhancements

- [ ] Multi-user support with Streamlit authentication
- [ ] Conversation export to PDF/JSON
- [ ] A/B testing framework for archetype variants
- [ ] Voice input/output (text-to-speech integration)
- [ ] Analytics dashboard (response latency, user engagement)
- [ ] Fine-tuning on GPU with Ray or Kubernetes
- [ ] Support for additional models (Mixtral, Phi, etc.)
- [ ] Real-time collaboration via WebSockets

---

## 11. Contact & References

- **Training Notebook**: `subscriber_sim_v2.ipynb` (Google Colab)
- **README**: Full project overview and usage
- **Makefile**: Quick reference for all commands
- **Modal Docs**: https://modal.com/docs
- **MLX Docs**: https://ml-explore.github.io/mlx/
- **Unsloth**: https://github.com/unslothai/unsloth
