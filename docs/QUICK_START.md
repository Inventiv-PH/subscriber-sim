# Quick Start Guide

## Prerequisites

- Python 3.12+
- ~5GB disk space (models + venv)
- For local inference: Mac with Apple Silicon or GPU with CUDA
- For cloud inference: Modal account (free tier available)

---

## Option 1: Run Locally (MLX Server + Streamlit)

### Step 1: Setup

```bash
cd /path/to/subscriber-sim
make setup
```

This creates a Python venv and installs:
- `mlx-lm` (local inference engine)
- `streamlit` (web UI)
- Other app dependencies

**Time**: ~3-5 minutes

### Step 2a: Convert Model Format (first time only)

```bash
make convert
```

Converts PEFT LoRA adapter → MLX-optimized format.

**Time**: ~2 minutes
**Output**: `models/finetuned-mlx/` directory

### Step 2b: Start Inference Server (Terminal 1)

```bash
make server
```

Starts MLX inference server on `http://localhost:8080`

**Expected output**:
```
Starting MLX server on localhost:8080…
Keep this terminal open. Start the app in another terminal.

Serving model mlx-community/Meta-Llama-3.1-8B-Instruct-4bit
Ready to accept requests
```

### Step 3: Start Streamlit App (Terminal 2)

```bash
make app
```

Opens the chat UI at `http://localhost:8501`

**Expected output**:
```
Starting Streamlit app on http://localhost:8501
Make sure MLX server is running (make server in another terminal).

  You can now view your Streamlit app in your browser.
  URL: http://localhost:8501
```

### Step 4: Use the App

1. **Select an archetype** (horny, cheapskate, casual, etc.)
2. **Type as Jasmin** (the chatbot will respond as the subscriber)
3. **View conversation history** in the sidebar
4. **Data is persisted** to `data/chat.db`

---

## Option 2: Run via Docker (Requires MLX Server Running)

### Step 1: Ensure MLX Server is Running

Follow "Option 1, Step 2-3" in another terminal first.

### Step 2: Start Docker Container

```bash
make docker-up
```

or manually:

```bash
docker compose up --build
```

App runs on `http://localhost:8501`

### Step 3: View Logs

```bash
make logs
```

### Step 4: Stop

```bash
make docker-down
```

---

## Option 3: Deploy to Modal (Cloud GPU)

### Step 1: Setup Modal

```bash
make modal-setup
```

Follow prompts to authenticate with your Modal account (free tier available).

### Step 2: Deploy Inference Server

```bash
make modal-deploy
```

Returns a URL like:
```
✅ Deployed. Copy the endpoint URL into docker-compose.yml → MLX_SERVER_URL
https://your-org--jasmin-inference.modal.run
```

### Step 3: Update Configuration

Edit `docker-compose.yml`:

```yaml
environment:
  - INFERENCE_BACKEND=modal
  - MLX_SERVER_URL=https://your-org--jasmin-inference.modal.run
```

### Step 4: Run App

```bash
docker compose up
```

App now queries Modal GPU instead of local MLX server.

---

## Quick Commands Reference

### Development

```bash
make setup           # Initial setup (venv + deps)
make convert         # Convert PEFT adapter → MLX
make server          # Start MLX inference (Terminal 1)
make app             # Start Streamlit (Terminal 2)
make clean           # Remove MLX cache + DB
make clean-all       # Remove everything (venv + models)
```

### Docker

```bash
make docker-up       # Build + start container
make docker-down     # Stop container
make logs            # Tail container logs
```

### Data Processing

```bash
make parse           # Parse raw chats → sessions.jsonl
```

### Cloud Deployment

```bash
make modal-setup     # Install + authenticate Modal
make modal-deploy    # Deploy inference to Modal GPU
make modal-serve     # Run Modal server locally (testing)
make hf-deploy HF_SPACE=yourname/jasmin-chat  # Deploy to HuggingFace
```

---

## Troubleshooting

### "Connection refused" when starting app

**Problem**: MLX server not running.

**Solution**:
```bash
# Terminal 1
make server

# Terminal 2 (different terminal)
make app
```

### "Port 8501 already in use"

**Solution**:
```bash
# Find process using port 8501
lsof -i :8501

# Kill it
kill -9 <PID>

# Or use a different port
streamlit run app/main.py --server.port 8502
```

### "CUDA out of memory" on GPU

**Problem**: Model too large for available VRAM.

**Solutions**:
- Reduce model size (switch to 7B model)
- Use quantization (already 4-bit, so already optimized)
- Use Modal cloud GPU instead

### Database locked error

**Problem**: Multiple processes accessing `data/chat.db` simultaneously.

**Solution**: Ensure only one Streamlit instance is running.

```bash
# Check running processes
ps aux | grep streamlit

# Kill any extra processes
kill -9 <PID>
```

### "Module not found" errors

**Problem**: Missing dependencies.

**Solution**:
```bash
# Reinstall dependencies
make clean-all
make setup
```

---

## File Structure (What Gets Created)

After `make setup && make convert`:

```
subscriber-sim/
├── venv/                          # Python virtual environment
├── data/
│   ├── chat.db                    # SQLite conversation database (created at runtime)
│   └── sessions.jsonl             # Pre-parsed training data
├── models/
│   ├── finetuned/                 # PEFT LoRA adapter (HuggingFace format)
│   └── finetuned-mlx/             # MLX-optimized adapter (created by make convert)
└── [other files...]
```

---

## Performance Tips

### Faster Responses

1. **Use Modal GPU** instead of local MLX (1-3 sec vs 2-5 sec)
2. **Reduce `max_tokens`** in `archetypes.py` (default: 80-100)
3. **Lower temperature** for faster convergence (e.g., 0.65 instead of 0.75)

### Less Memory Usage

1. Use MLX instead of CUDA (more efficient on Mac)
2. Close other apps while running server
3. Consider smaller model variant (3B instead of 8B)

### Database Performance

Already optimized with:
- WAL (Write-Ahead Logging) mode
- Indexes on conversation_id and created_at
- Thread-safe locking

---

## Next Steps

- **Fine-tune on new data**: See `subscriber_sim_v2.ipynb` (Google Colab)
- **Understand architecture**: Read `docs/ARCHITECTURE.md`
- **Process raw chats**: `make parse` then `scripts/parse_chats.py`
- **Deploy to production**: `make modal-deploy` + Docker
- **Contribute**: Submit PRs for improvements

---

## Useful Env Variables

```bash
# Logging
export DEBUG=true              # Verbose logging

# Database location
export DB_PATH=/custom/path/chat.db

# MLX Server (if using local)
export MLX_SERVER_URL=http://localhost:8080
export MODEL_NAME=mlx-community/Meta-Llama-3.1-8B-Instruct-4bit

# Modal (if using cloud)
export INFERENCE_BACKEND=modal
export MODAL_TOKEN_ID=<your-id>
export MODAL_TOKEN_SECRET=<your-secret>

# Apply before starting app
make app
```

---

## Support

- **Issues**: Check `docs/ARCHITECTURE.md` section 8 (Error Handling)
- **Logs**: `docker compose logs chat` or check stdout from `make server`
- **Data**: All conversations saved to `data/chat.db` (auto-backed up)

Enjoy! 🚀
